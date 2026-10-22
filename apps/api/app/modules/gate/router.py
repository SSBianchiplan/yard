from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Principal, Role, actor_of, current_principal, requires, with_actor
from app.modules.gate import service
from app.modules.gate.models import AccessCommand, Device, IdentificationEvent
from app.modules.gate.schemas import (
    ChecklistAnswerIn,
    ChecklistItemOut,
    CommandIn,
    CommandOut,
    DeviceOut,
    EscortIn,
    IdentifyIn,
    ScreeningOut,
)

router = APIRouter(
    prefix="/gate",
    tags=["gate"],
    dependencies=[Depends(requires(Role.GATE, Role.SUPERVISOR))],
)


@router.post("/identify", response_model=ScreeningOut)
async def identify(
    data: IdentifyIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(current_principal),
) -> ScreeningOut:
    """LPR, QR, RFID, crachá ou digitação → decisão de triagem. Não comanda cancela."""
    return await service.identify(session, with_actor(data, principal, "actor"))


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices(
    session: AsyncSession = Depends(get_session), kind: str | None = None
) -> list[DeviceOut]:
    stmt = select(Device).order_by(Device.code)
    if kind:
        stmt = stmt.where(Device.kind == kind)
    return [
        DeviceOut.model_validate(device)
        for device in (await session.execute(stmt)).scalars().all()
    ]


@router.get("/visits/{visit_id}/checklist", response_model=list[ChecklistItemOut])
async def checklist(
    visit_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[ChecklistItemOut]:
    items = await service.required_items(session, visit_id)
    return [ChecklistItemOut.model_validate(item) for item in items]


@router.post("/visits/{visit_id}/checklist", response_model=list[str])
async def answer_checklist(
    visit_id: UUID,
    data: ChecklistAnswerIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(current_principal),
) -> list[str]:
    """Devolve os códigos dos itens bloqueantes reprovados — lista vazia é o bom caso."""
    return await service.answer_checklist(session, visit_id, with_actor(data, principal, "actor"))


@router.post("/command", response_model=CommandOut)
async def command(
    data: CommandIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(current_principal),
) -> CommandOut:
    # Quem autoriza é quem autenticou. Quem APROVOU um comando de IA não é declarado
    # pelo cliente: vem da proposta aprovada na torre (o trigger do banco confere de novo).
    approved_by = None
    if data.origin == "ai" and data.ai_proposal_id:
        from app.modules.tower.models import AiProposal

        proposal = await session.get(AiProposal, data.ai_proposal_id)
        if proposal is not None and proposal.state in ("approved", "executed"):
            approved_by = proposal.approved_by
    data = data.model_copy(
        update={
            "authorized_by": actor_of(principal, data.authorized_by),
            "approved_by": approved_by,
        }
    )
    cmd = await service.command(session, data)
    return CommandOut.model_validate(cmd)


@router.get("/commands", response_model=list[CommandOut])
async def list_commands(
    session: AsyncSession = Depends(get_session), limit: int = Query(default=100, le=500)
) -> list[CommandOut]:
    rows = (
        await session.execute(
            select(AccessCommand).order_by(AccessCommand.requested_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [CommandOut.model_validate(row) for row in rows]


@router.get("/identifications")
async def list_identifications(
    session: AsyncSession = Depends(get_session),
    gate_code: str | None = None,
    limit: int = Query(default=50, le=500),
):
    from app.modules.yard.models import Gate

    stmt = (
        select(IdentificationEvent)
        .order_by(IdentificationEvent.occurred_at.desc())
        .limit(limit)
    )
    if gate_code:
        stmt = stmt.join(Gate, Gate.id == IdentificationEvent.gate_id).where(
            Gate.code == gate_code
        )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "occurred_at": row.occurred_at,
            "method": row.method,
            "value": row.normalized_value,
            "confidence": row.confidence,
            "state": row.state,
            "image_ref": row.image_ref,
        }
        for row in rows
    ]


@router.post("/visits/{visit_id}/escorts", status_code=201)
async def add_escort(
    visit_id: UUID, data: EscortIn, session: AsyncSession = Depends(get_session)
):
    escort = await service.register_escort(session, visit_id, data)
    return {"id": escort.id, "full_name": escort.full_name, "role": escort.role}


@router.get("/self-service/{appointment_reference}")
async def self_service(appointment_reference: str, session: AsyncSession = Depends(get_session)):
    """Token do totem/QR/WhatsApp. O fallback humano continua valendo sempre."""
    token = await service.self_service_token(session, appointment_reference)
    return {"token": token, "fallback": "human_guard"}
