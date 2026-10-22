"""Integrações: outbox transacional, documento fiscal brasileiro e notificação.

Três decisões que evitam a dor clássica de integração:
  1. **outbox na mesma transação do fato** — se o fato existe, a mensagem existe;
  2. **idempotência de verdade** — chave por cliente, resposta repetida em vez de efeito novo;
  3. **dead-letter visível** — mensagem que falhou demais aparece na tela, não some no log.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_NOT_FOUND,
    ERR_YARD_FISCAL_KEY_INVALID,
    ERR_YARD_NOTIFICATION_OPTED_OUT,
    Conflict,
    NotFound,
)
from app.core.events import hub
from app.modules.integrations.models import (
    ApiRequest,
    DeliveryLog,
    FiscalDocument,
    IntegrationEndpoint,
    Notification,
    NotificationOptOut,
    OutboxMessage,
)
from app.modules.integrations.schemas import FiscalDocumentIn, NotificationIn


def now() -> datetime:
    return datetime.now(timezone.utc)


async def _one(session: AsyncSession, stmt, entity: str, **params: Any):
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, **params)
    return obj


# ----------------------------- outbox -----------------------------


async def enqueue(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    endpoint_code: str | None = None,
    event_seq: int | None = None,
) -> OutboxMessage:
    """Enfileira SEM commit: quem chama decide a transação — esse é o ponto do outbox."""
    endpoint_id = None
    max_retry = 8
    if endpoint_code:
        endpoint = await _one(
            session,
            select(IntegrationEndpoint).where(IntegrationEndpoint.code == endpoint_code),
            entity="integration_endpoint",
            code=endpoint_code,
        )
        endpoint_id = endpoint.id
        max_retry = endpoint.max_retry

    message = OutboxMessage(
        created_at=now(),
        endpoint_id=endpoint_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_seq=event_seq or int(now().timestamp() * 1000),
        event_type=event_type,
        payload=payload,
        state="pending",
        max_retry=max_retry,
        next_attempt_at=now(),
    )
    session.add(message)
    return message


async def dispatch(session: AsyncSession, limit: int = 50) -> dict[str, int]:
    """Publica o que está pendente. Falha vira retry com recuo; retry esgotado vira
    dead-letter — que fica na tela, porque mensagem perdida em silêncio é o pior caso.
    """
    messages = (
        await session.execute(
            select(OutboxMessage)
            .where(
                OutboxMessage.state.in_(("pending", "failed")),
                OutboxMessage.next_attempt_at <= now(),
            )
            .order_by(OutboxMessage.created_at)
            .limit(limit)
        )
    ).scalars().all()

    sent = failed = dead = 0
    for message in messages:
        try:
            await _publish(session, message)
            message.state = "sent"
            message.sent_at = now()
            sent += 1
        except Exception as exc:  # noqa: BLE001 - publicação externa falha de tudo quanto é jeito
            message.retry_count += 1
            message.last_error = str(exc)[:300]
            if message.retry_count > message.max_retry:
                message.state = "dead_letter"
                dead += 1
            else:
                message.state = "failed"
                # Recuo exponencial com teto: 2^n segundos, no máximo 1h.
                delay = min(3600, 2**message.retry_count)
                message.next_attempt_at = now() + timedelta(seconds=delay)
                failed += 1
    await session.commit()
    if dead:
        await hub.publish("yard.integration.dead_letter", {"count": dead})
    return {"sent": sent, "failed": failed, "dead_letter": dead}


async def _publish(session: AsyncSession, message: OutboxMessage) -> None:
    """Entrega ao destino.

    Sem endpoint configurado, a mensagem é publicada no barramento interno — é o que
    permite desenvolver e demonstrar sem ERP nenhum do outro lado.
    """
    await hub.publish(f"outbox.{message.event_type}", message.payload)


async def retry(session: AsyncSession, message_id: UUID) -> OutboxMessage:
    message = await _one(
        session,
        select(OutboxMessage).where(OutboxMessage.id == message_id),
        entity="outbox_message",
    )
    message.state = "pending"
    message.next_attempt_at = now()
    message.last_error = None
    await session.commit()
    return message


# ----------------------------- idempotência -----------------------------


async def idempotent(
    session: AsyncSession, client_id: str, key: str, method: str, path: str
) -> dict[str, Any] | None:
    """Devolve a resposta anterior quando a chave repete. Mesma chave, mesmo efeito."""
    existing = (
        await session.execute(
            select(ApiRequest).where(
                ApiRequest.client_id == client_id, ApiRequest.idempotency_key == key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.response_json
    session.add(
        ApiRequest(
            created_at=now(),
            client_id=client_id,
            idempotency_key=key,
            method=method,
            path=path,
        )
    )
    await session.commit()
    return None


async def record_response(
    session: AsyncSession, client_id: str, key: str, status_code: int, body: dict[str, Any]
) -> None:
    request = (
        await session.execute(
            select(ApiRequest).where(
                ApiRequest.client_id == client_id, ApiRequest.idempotency_key == key
            )
        )
    ).scalar_one_or_none()
    if request is not None:
        request.status_code = status_code
        request.response_json = body
        await session.commit()


# ----------------------------- fiscal -----------------------------


def validate_access_key(key: str) -> bool:
    """Valida a chave de 44 dígitos com o dígito verificador (módulo 11), como a SEFAZ."""
    if len(key) != 44 or not key.isdigit():
        return False
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    for index, digit in enumerate(reversed(key[:43])):
        total += int(digit) * weights[index % 8]
    remainder = total % 11
    check = 0 if remainder in (0, 1) else 11 - remainder
    return check == int(key[43])


async def register_fiscal(session: AsyncSession, data: FiscalDocumentIn) -> FiscalDocument:
    if data.kind in ("nfe", "cte", "mdfe"):
        if not data.access_key or not validate_access_key(data.access_key):
            raise Conflict(ERR_YARD_FISCAL_KEY_INVALID, kind=data.kind, key=data.access_key)

    document = FiscalDocument(
        visit_id=data.visit_id,
        kind=data.kind,
        access_key=data.access_key,
        number=data.number,
        series=data.series,
        issuer_tax_id=data.issuer_tax_id,
        net_weight_kg=data.net_weight_kg,
        state="validated" if data.kind in ("nfe", "cte", "mdfe") else "received",
        validated_at=now() if data.kind in ("nfe", "cte", "mdfe") else None,
        payload=data.payload,
        created_at=now(),
        updated_at=now(),
    )
    session.add(document)
    await enqueue(
        session,
        aggregate_type="fiscal_document",
        aggregate_id=data.visit_id or UUID(int=0),
        event_type="fiscal.registered",
        payload={"kind": data.kind, "access_key": data.access_key},
    )
    await session.commit()
    return document


# ----------------------------- notificação -----------------------------


async def notify(session: AsyncSession, data: NotificationIn) -> Notification:
    """Cria a notificação. O trigger marca opt-out; enviar a quem saiu não acontece."""
    notification = Notification(
        created_at=now(),
        visit_id=data.visit_id,
        appointment_id=data.appointment_id,
        channel=data.channel,
        address=data.address,
        template_code=data.template_code,
        params=data.params,
        state="queued",
    )
    session.add(notification)
    await session.commit()
    # O trigger decide o opt-out dentro do INSERT: sem reler, a sessão acredita no
    # 'queued' que ela mesma escreveu e manda mensagem para quem pediu para não receber.
    await session.refresh(notification)

    if notification.state == "opted_out":
        raise Conflict(
            ERR_YARD_NOTIFICATION_OPTED_OUT, channel=data.channel, address=data.address
        )

    session.add(
        DeliveryLog(notification_id=notification.id, occurred_at=now(), state="queued")
    )
    await session.commit()
    return notification


async def mark_delivery(
    session: AsyncSession, notification_id: UUID, state: str, detail: str | None = None
) -> Notification:
    notification = await _one(
        session,
        select(Notification).where(Notification.id == notification_id),
        entity="notification",
    )
    notification.state = state
    if state == "sent":
        notification.sent_at = now()
    elif state == "delivered":
        notification.delivered_at = now()
    elif state == "read":
        notification.read_at = now()
    elif state == "failed":
        notification.failure_code = detail[:48] if detail else "UNKNOWN"
    session.add(
        DeliveryLog(
            notification_id=notification.id, occurred_at=now(), state=state, detail=detail
        )
    )
    await session.commit()
    return notification


async def opt_out(session: AsyncSession, channel: str, address: str, reason: str | None = None):
    session.add(
        NotificationOptOut(
            channel=channel, address=address, opted_out_at=now(), reason_code=reason
        )
    )
    await session.commit()


# ----------------------------- BI -----------------------------


async def kpi_snapshot(session: AsyncSession) -> dict[str, Any]:
    """Snapshot para BI: os KPIs do §3.12 num payload só, com hash para conferência."""
    row = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM visit WHERE gate_in_at >= date_trunc('day', now()))
                      AS gate_in_today,
                  (SELECT count(*) FROM visit WHERE gate_out_at >= date_trunc('day', now()))
                      AS gate_out_today,
                  COALESCE((SELECT avg(EXTRACT(EPOCH FROM (gate_in_at - arrived_at)))
                     FROM visit WHERE gate_in_at >= now() - interval '7 days'), 0)
                      AS avg_gate_in_seconds,
                  COALESCE((SELECT avg(EXTRACT(EPOCH FROM (gate_out_at - arrived_at)))
                     FROM visit WHERE gate_out_at >= now() - interval '7 days'), 0)
                      AS avg_dwell_seconds,
                  COALESCE((SELECT 100.0 * count(*) FILTER (WHERE source IN ('device','system'))
                            / NULLIF(count(*), 0)
                     FROM visit_event WHERE occurred_at >= now() - interval '24 hours'), 0)
                      AS automatic_event_pct,
                  COALESCE((SELECT avg(abs(divergence_pct)) FROM weighing_ticket
                     WHERE state = 'closed' AND closed_at >= now() - interval '7 days'), 0)
                      AS avg_weight_divergence_pct,
                  (SELECT count(*) FROM outbox_message WHERE state = 'dead_letter')
                      AS dead_letters
                """
            )
        )
    ).mappings().one()
    snapshot = {k: float(v) if v is not None else 0.0 for k, v in dict(row).items()}
    snapshot["generated_at"] = now().isoformat()
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    snapshot["hash"] = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return snapshot
