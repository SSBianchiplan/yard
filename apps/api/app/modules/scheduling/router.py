from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires
from app.core.errors import ERR_NOT_FOUND, NotFound
from app.modules.catalog.models import Carrier, OperationType, Product, Vehicle
from app.modules.scheduling import service
from app.modules.scheduling.models import Appointment, AppointmentChangeLog, Resource
from app.modules.scheduling.schemas import (
    AppointmentIn,
    AppointmentOut,
    AvailabilityWindow,
    CancelIn,
    ChangeLogOut,
    ConfirmIn,
    ImpactOut,
    RescheduleIn,
)
from app.modules.yard.models import Dock, Slot

router = APIRouter(
    prefix="/scheduling",
    tags=["scheduling"],
    dependencies=[Depends(requires(Role.SCHEDULER, Role.CONTROLLER))],
)


def _projection() -> Select:
    return (
        select(
            Appointment,
            Dock.code.label("dock_code"),
            Vehicle.plate,
            Carrier.name.label("carrier_name"),
            Product.name.label("product_name"),
            OperationType.code.label("operation_type_code"),
            Resource.code.label("resource_code"),
            Slot.code.label("slot_code"),
        )
        .join(Dock, Dock.id == Appointment.dock_id)
        .join(Vehicle, Vehicle.id == Appointment.vehicle_id)
        .join(OperationType, OperationType.id == Appointment.operation_type_id)
        .outerjoin(Carrier, Carrier.id == Appointment.carrier_id)
        .outerjoin(Product, Product.id == Appointment.product_id)
        .outerjoin(Resource, Resource.id == Appointment.resource_id)
        .outerjoin(Slot, Slot.id == Appointment.slot_id)
    )


def _to_out(row) -> AppointmentOut:
    appointment: Appointment = row[0]
    return AppointmentOut(
        id=appointment.id,
        reference=appointment.reference,
        state=appointment.state,
        version=appointment.version,
        dock_code=row.dock_code,
        plate=row.plate,
        carrier_name=row.carrier_name,
        product_name=row.product_name,
        operation_type_code=row.operation_type_code,
        resource_code=row.resource_code,
        slot_code=row.slot_code,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        priority_code=appointment.priority_code,
        priority_rank=appointment.priority_rank,
        channel=appointment.channel,
        visit_id=appointment.visit_id,
    )


async def _reload(session: AsyncSession, appointment_id: UUID) -> AppointmentOut:
    row = (await session.execute(_projection().where(Appointment.id == appointment_id))).first()
    if row is None:
        raise NotFound(ERR_NOT_FOUND, entity="appointment", id=str(appointment_id))
    return _to_out(row)


@router.get("/appointments", response_model=list[AppointmentOut])
async def list_appointments(
    session: AsyncSession = Depends(get_session),
    dock_code: str | None = None,
    state: list[str] | None = Query(default=None),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=500, le=2000),
) -> list[AppointmentOut]:
    stmt = _projection()
    if dock_code:
        stmt = stmt.where(Dock.code == dock_code)
    if state:
        stmt = stmt.where(Appointment.state.in_(state))
    if date_from:
        stmt = stmt.where(Appointment.ends_at >= date_from)
    if date_to:
        stmt = stmt.where(Appointment.starts_at <= date_to)
    stmt = stmt.order_by(Appointment.starts_at).limit(limit)
    return [_to_out(row) for row in (await session.execute(stmt)).all()]


@router.get("/availability", response_model=list[AvailabilityWindow])
async def availability(
    session: AsyncSession = Depends(get_session),
    date_from: datetime | None = None,
    hours: int = Query(default=12, le=72),
    slot_minutes: int = Query(default=60, ge=15, le=240),
    dock_code: str | None = None,
) -> list[AvailabilityWindow]:
    """Grade de janelas por doca. Capacidade finita fica visível antes de alguém tentar."""
    start = (date_from or service.now()).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=hours)

    docks_stmt = select(Dock).order_by(Dock.code)
    if dock_code:
        docks_stmt = docks_stmt.where(Dock.code == dock_code)
    docks = (await session.execute(docks_stmt)).scalars().all()

    taken = (
        await session.execute(
            select(Appointment).where(
                Appointment.state.in_(service.ACTIVE_STATES),
                Appointment.starts_at < end,
                Appointment.ends_at > start,
            )
        )
    ).scalars().all()

    windows: list[AvailabilityWindow] = []
    for dock in docks:
        cursor = start
        while cursor < end:
            window_end = cursor + timedelta(minutes=slot_minutes)
            busy = any(
                a.dock_id == dock.id and a.starts_at < window_end and a.ends_at > cursor
                for a in taken
            )
            reason = None
            # `occupied` é estado de agora, não de calendário: doca ocupada às 14h
            # continua agendável às 18h. Só bloqueio real fecha a janela.
            if dock.status == "blocked":
                busy, reason = True, "ERR_YARD_SLOT_BLOCKED"
            elif busy:
                reason = "ERR_YARD_DOCK_WINDOW_TAKEN"
            windows.append(
                AvailabilityWindow(
                    dock_code=dock.code,
                    starts_at=cursor,
                    ends_at=window_end,
                    available=not busy,
                    reason_code=reason,
                )
            )
            cursor = window_end
    return windows


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
async def create_appointment(
    data: AppointmentIn, session: AsyncSession = Depends(get_session)
) -> AppointmentOut:
    appointment = await service.create(session, data)
    return await _reload(session, appointment.id)


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentOut)
async def confirm_appointment(
    appointment_id: UUID, data: ConfirmIn, session: AsyncSession = Depends(get_session)
) -> AppointmentOut:
    await service.confirm(session, appointment_id, data)
    return await _reload(session, appointment_id)


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentOut)
async def reschedule_appointment(
    appointment_id: UUID, data: RescheduleIn, session: AsyncSession = Depends(get_session)
) -> AppointmentOut:
    await service.reschedule(session, appointment_id, data)
    return await _reload(session, appointment_id)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment(
    appointment_id: UUID, data: CancelIn, session: AsyncSession = Depends(get_session)
) -> AppointmentOut:
    await service.cancel(session, appointment_id, data)
    return await _reload(session, appointment_id)


@router.post("/appointments/{appointment_id}/no-show", response_model=AppointmentOut)
async def no_show(
    appointment_id: UUID,
    actor: str = Body(embed=True),
    session: AsyncSession = Depends(get_session),
) -> AppointmentOut:
    """Não compareceu: libera a janela e a vaga reservada, com rastro de quem marcou."""
    await service.mark_no_show(session, appointment_id, actor)
    return await _reload(session, appointment_id)


@router.get("/appointments/{appointment_id}/impact", response_model=ImpactOut)
async def appointment_impact(
    appointment_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    dock_code: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> ImpactOut:
    appointment = (
        await session.execute(select(Appointment).where(Appointment.id == appointment_id))
    ).scalar_one_or_none()
    if appointment is None:
        raise NotFound(ERR_NOT_FOUND, entity="appointment", id=str(appointment_id))
    return await service.compute_impact(session, appointment, starts_at, ends_at, dock_code)


@router.get("/appointments/{appointment_id}/history", response_model=list[ChangeLogOut])
async def appointment_history(
    appointment_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[ChangeLogOut]:
    rows = (
        await session.execute(
            select(AppointmentChangeLog)
            .where(AppointmentChangeLog.appointment_id == appointment_id)
            .order_by(AppointmentChangeLog.occurred_at.desc())
        )
    ).scalars().all()
    return [ChangeLogOut.model_validate(row) for row in rows]
