"""Integrações: outbox que não perde, idempotência que não duplica, opt-out que vale."""

import pytest
from sqlalchemy import select, text

from app.core.errors import ERR_YARD_FISCAL_KEY_INVALID, ERR_YARD_NOTIFICATION_OPTED_OUT, Conflict
from app.modules.integrations import service
from app.modules.integrations.models import Notification, OutboxMessage
from app.modules.integrations.schemas import FiscalDocumentIn, NotificationIn
from app.modules.visits import service as visit_service
from app.modules.visits.schemas import GateInIn


def _valid_key() -> str:
    """Monta uma chave de 44 dígitos com DV correto (módulo 11), como a SEFAZ faria."""
    base = "3526091234567890001255001000000123100000012"
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = sum(int(d) * weights[i % 8] for i, d in enumerate(reversed(base)))
    remainder = total % 11
    check = 0 if remainder in (0, 1) else 11 - remainder
    return base + str(check)


async def _visit(session):
    return await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A01",
            driver_document="10000000001",
            operation_type_code="RECEBIMENTO_GRANEL",
        ),
    )


async def test_gate_in_publica_no_outbox_na_mesma_transacao(session, fixture_yard):
    """O fato e a mensagem nascem juntos: o trigger do banco garante isso."""
    visit = await _visit(session)
    messages = (
        await session.execute(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id)
        )
    ).scalars().all()
    assert messages, "gate-in tem de deixar mensagem no outbox"
    assert messages[0].event_type == "visit.gate_in"
    assert messages[0].state == "pending"


async def test_mesmo_evento_nao_entra_duas_vezes_no_outbox(session, fixture_yard):
    visit = await _visit(session)
    await service.enqueue(
        session,
        aggregate_type="visit",
        aggregate_id=visit.id,
        event_type="visit.custom",
        payload={"a": 1},
        event_seq=42,
    )
    await session.commit()

    # Mesma (agregado, sequência, tipo): o índice único recusa a segunda.
    await service.enqueue(
        session,
        aggregate_type="visit",
        aggregate_id=visit.id,
        event_type="visit.custom",
        payload={"a": 1},
        event_seq=42,
    )
    with pytest.raises(Exception):
        await session.commit()
    await session.rollback()


async def test_dispatch_marca_enviado_e_e_repetivel(session, fixture_yard):
    await _visit(session)
    first = await service.dispatch(session)
    assert first["sent"] >= 1
    # Rodar de novo não reenvia o que já saiu.
    second = await service.dispatch(session)
    assert second["sent"] == 0


async def test_retry_esgotado_vira_dead_letter_visivel(session, fixture_yard):
    visit = await _visit(session)
    message = (
        await session.execute(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id)
        )
    ).scalars().first()
    message_id = message.id
    await session.execute(
        text(
            "UPDATE outbox_message SET state = 'failed', retry_count = max_retry,"
            " next_attempt_at = now() WHERE id = :id"
        ),
        {"id": message_id},
    )
    await session.commit()
    session.expire_all()  # o UPDATE foi cru; a sessão ainda tinha a versão antiga

    # Falha forçada na publicação: a próxima tentativa estoura o limite.
    original = service._publish

    async def boom(_session, _message):
        raise RuntimeError("endpoint fora do ar")

    service._publish = boom
    try:
        result = await service.dispatch(session)
    finally:
        service._publish = original

    assert result["dead_letter"] >= 1
    state = (
        await session.execute(
            text("SELECT state FROM outbox_message WHERE id = :id"), {"id": message_id}
        )
    ).scalar_one()
    assert state == "dead_letter"


async def test_idempotencia_devolve_a_mesma_resposta(session, fixture_yard):
    first = await service.idempotent(session, "erp-sap", "abc-123", "POST", "/visits/gate-in")
    assert first is None  # primeira vez: segue o fluxo normal
    await service.record_response(session, "erp-sap", "abc-123", 201, {"reference": "YRD-1"})

    again = await service.idempotent(session, "erp-sap", "abc-123", "POST", "/visits/gate-in")
    assert again == {"reference": "YRD-1"}


async def test_chave_fiscal_invalida_e_recusada(session, fixture_yard):
    with pytest.raises(Conflict) as exc:
        await service.register_fiscal(
            session, FiscalDocumentIn(kind="nfe", access_key="123")
        )
    assert exc.value.code == ERR_YARD_FISCAL_KEY_INVALID


async def test_chave_fiscal_valida_e_aceita_e_publicada(session, fixture_yard):
    visit = await _visit(session)
    key = _valid_key()
    document = await service.register_fiscal(
        session,
        FiscalDocumentIn(kind="nfe", access_key=key, visit_id=visit.id, net_weight_kg=30000),
    )
    assert document.state == "validated" and document.access_key == key

    published = (
        await session.execute(
            select(OutboxMessage).where(OutboxMessage.event_type == "fiscal.registered")
        )
    ).scalars().all()
    assert published


async def test_opt_out_bloqueia_envio_em_qualquer_canal(session, fixture_yard):
    await service.opt_out(session, "whatsapp", "+5515990000000", "DRIVER_REQUEST")

    with pytest.raises(Conflict) as exc:
        await service.notify(
            session,
            NotificationIn(
                channel="whatsapp",
                address="+5515990000000",
                template_code="GATE_IN_OK",
            ),
        )
    assert exc.value.code == ERR_YARD_NOTIFICATION_OPTED_OUT

    stored = (
        await session.execute(
            select(Notification).where(Notification.address == "+5515990000000")
        )
    ).scalars().first()
    assert stored.state == "opted_out" and stored.opted_out is True


async def test_notificacao_registra_log_de_entrega(session, fixture_yard):
    notification = await service.notify(
        session,
        NotificationIn(channel="sms", address="+5515991111111", template_code="GATE_IN_OK"),
    )
    notification_id = notification.id
    await service.mark_delivery(session, notification_id, "sent")
    await service.mark_delivery(session, notification_id, "delivered")

    log = (
        await session.execute(
            text(
                "SELECT state FROM delivery_log WHERE notification_id = :id"
                " ORDER BY occurred_at"
            ),
            {"id": notification_id},
        )
    ).scalars().all()
    assert log == ["queued", "sent", "delivered"]


async def test_snapshot_de_kpi_para_bi(session, fixture_yard):
    await _visit(session)
    snapshot = await service.kpi_snapshot(session)
    assert snapshot["gate_in_today"] >= 0
    assert "hash" in snapshot and len(snapshot["hash"]) == 16
