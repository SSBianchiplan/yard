from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires
from app.modules.integrations import service
from app.modules.integrations.models import (
    DeliveryLog,
    FiscalDocument,
    InboxMessage,
    IntegrationEndpoint,
    Notification,
    OutboxMessage,
)
from app.modules.integrations.schemas import (
    EndpointIn,
    FiscalDocumentIn,
    FiscalDocumentOut,
    NotificationIn,
    NotificationOut,
    OutboxOut,
)

router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
    dependencies=[Depends(requires(Role.ADMIN, Role.CONTROLLER))],
)


@router.get("/endpoints")
async def endpoints(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(select(IntegrationEndpoint).order_by(IntegrationEndpoint.code))
    ).scalars().all()
    return [
        {
            "code": row.code,
            "system": row.system,
            "direction": row.direction,
            "active": row.active,
            "max_retry": row.max_retry,
        }
        for row in rows
    ]


@router.post("/endpoints", status_code=201)
async def create_endpoint(data: EndpointIn, session: AsyncSession = Depends(get_session)):
    endpoint = IntegrationEndpoint(**data.model_dump())
    session.add(endpoint)
    await session.commit()
    return {"id": endpoint.id, "code": endpoint.code}


@router.get("/outbox", response_model=list[OutboxOut])
async def outbox(
    session: AsyncSession = Depends(get_session),
    state: str | None = None,
    limit: int = Query(default=100, le=500),
) -> list[OutboxOut]:
    stmt = select(OutboxMessage).order_by(OutboxMessage.created_at.desc()).limit(limit)
    if state:
        stmt = stmt.where(OutboxMessage.state == state)
    rows = (await session.execute(stmt)).scalars().all()
    return [OutboxOut.model_validate(row) for row in rows]


@router.post("/outbox/dispatch")
async def dispatch(
    session: AsyncSession = Depends(get_session), limit: int = Query(default=50, le=500)
):
    """Publica o que está pendente. Idempotente: rodar duas vezes não duplica entrega."""
    return await service.dispatch(session, limit)


@router.post("/outbox/{message_id}/retry", response_model=OutboxOut)
async def retry(message_id: UUID, session: AsyncSession = Depends(get_session)) -> OutboxOut:
    return OutboxOut.model_validate(await service.retry(session, message_id))


@router.post("/webhooks/{endpoint_code}")
async def webhook(
    endpoint_code: str,
    request: Request,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    x_external_id: str | None = Header(default=None),
):
    """Entrada externa idempotente: o mesmo `X-External-Id` não é processado duas vezes."""
    endpoint = (
        await session.execute(
            select(IntegrationEndpoint).where(IntegrationEndpoint.code == endpoint_code)
        )
    ).scalar_one_or_none()
    external_id = x_external_id or str(hash(str(payload)))

    existing = (
        await session.execute(
            select(InboxMessage).where(
                InboxMessage.endpoint_id == (endpoint.id if endpoint else None),
                InboxMessage.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"state": "duplicate", "id": existing.id}

    message = InboxMessage(
        received_at=service.now(),
        endpoint_id=endpoint.id if endpoint else None,
        external_id=external_id,
        event_type=payload.get("event_type", "unknown"),
        payload=payload,
        state="received",
    )
    session.add(message)
    await session.commit()
    return {"state": "received", "id": message.id, "path": request.url.path}


@router.post("/fiscal/documents", response_model=FiscalDocumentOut, status_code=201)
async def register_fiscal(
    data: FiscalDocumentIn, session: AsyncSession = Depends(get_session)
) -> FiscalDocumentOut:
    """NF-e/CT-e/MDF-e com validação de chave (44 dígitos + DV módulo 11)."""
    return FiscalDocumentOut.model_validate(await service.register_fiscal(session, data))


@router.get("/fiscal/documents", response_model=list[FiscalDocumentOut])
async def list_fiscal(
    session: AsyncSession = Depends(get_session), visit_id: UUID | None = None
) -> list[FiscalDocumentOut]:
    stmt = select(FiscalDocument).order_by(FiscalDocument.created_at.desc()).limit(200)
    if visit_id:
        stmt = stmt.where(FiscalDocument.visit_id == visit_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [FiscalDocumentOut.model_validate(row) for row in rows]


@router.post("/notifications", response_model=NotificationOut, status_code=201)
async def notify(
    data: NotificationIn, session: AsyncSession = Depends(get_session)
) -> NotificationOut:
    return NotificationOut.model_validate(await service.notify(session, data))


@router.post("/notifications/{notification_id}/delivery", response_model=NotificationOut)
async def delivery(
    notification_id: UUID,
    state: str = Body(embed=True),
    detail: str | None = Body(default=None, embed=True),
    session: AsyncSession = Depends(get_session),
) -> NotificationOut:
    return NotificationOut.model_validate(
        await service.mark_delivery(session, notification_id, state, detail)
    )


@router.get("/notifications/{notification_id}/log")
async def delivery_log(notification_id: UUID, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(DeliveryLog)
            .where(DeliveryLog.notification_id == notification_id)
            .order_by(DeliveryLog.occurred_at)
        )
    ).scalars().all()
    return [
        {"occurred_at": row.occurred_at, "state": row.state, "detail": row.detail}
        for row in rows
    ]


@router.post("/notifications/opt-out", status_code=201)
async def opt_out(
    channel: str = Body(embed=True),
    address: str = Body(embed=True),
    reason_code: str | None = Body(default=None, embed=True),
    session: AsyncSession = Depends(get_session),
):
    """Opt-out vale para todos os canais automáticos, inclusive os do sistema."""
    await service.opt_out(session, channel, address, reason_code)
    return {"channel": channel, "address": address, "state": "opted_out"}


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    session: AsyncSession = Depends(get_session), limit: int = Query(default=100, le=500)
) -> list[NotificationOut]:
    rows = (
        await session.execute(
            select(Notification).order_by(Notification.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [NotificationOut.model_validate(row) for row in rows]


@router.get("/bi/kpi-snapshot")
async def kpi_snapshot(session: AsyncSession = Depends(get_session)):
    """Snapshot dos KPIs para BI, com hash — o mesmo número em todo lugar."""
    return await service.kpi_snapshot(session)
