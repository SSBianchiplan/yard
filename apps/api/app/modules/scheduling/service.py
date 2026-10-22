"""Agendamento: capacidade finita nos três eixos, prioridade como dado, rastro em tudo.

Confirmar um agendamento consome, ao mesmo tempo: janela da doca, capacidade do recurso de
descarga e (quando o tipo de operação pede espera) uma vaga reservada. Se qualquer um
estourar, não confirma — meio agendamento não existe.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_NOT_FOUND,
    ERR_YARD_APPOINTMENT_STALE,
    ERR_YARD_DOCK_WINDOW_TAKEN,
    ERR_YARD_INVALID_TRANSITION,
    ERR_YARD_PLANT_STOPPAGE,
    ERR_YARD_RESOURCE_EXHAUSTED,
    ERR_YARD_SHIFT_CLOSED,
    ERR_YARD_SLOT_OCCUPIED,
    Conflict,
    NotFound,
)
from app.core.events import hub
from app.modules.catalog.models import Driver, OperationType, Product, Vehicle
from app.modules.scheduling.models import (
    Appointment,
    AppointmentChangeLog,
    PlantStoppage,
    PriorityRule,
    Resource,
    ShiftCalendar,
    SlotReservation,
)
from app.modules.scheduling.schemas import (
    AppointmentIn,
    CancelIn,
    ConfirmIn,
    ImpactOut,
    RescheduleIn,
)
from app.modules.yard.models import Dock, Slot, SlotOccupancy

ACTIVE_STATES = ("confirmed", "checked_in", "in_progress")
OPEN_STATES = ("requested", *ACTIVE_STATES)


def now() -> datetime:
    return datetime.now(timezone.utc)


async def _one(session: AsyncSession, stmt, entity: str, **params: Any):
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, **params)
    return obj


async def _plant_id(session: AsyncSession) -> UUID:
    return (await session.execute(text("SELECT id FROM plant ORDER BY code LIMIT 1"))).scalar_one()


async def _reference(session: AsyncSession) -> str:
    seq = (
        await session.execute(text("SELECT nextval('appointment_reference_seq')"))
    ).scalar_one()
    return f"APT-{date.today().year}-{seq:06d}"


async def _log(
    session: AsyncSession,
    appointment: Appointment,
    *,
    actor: str | None,
    reason_code: str | None,
    from_state: str | None,
    to_state: str | None,
    from_starts_at: datetime | None = None,
    to_starts_at: datetime | None = None,
    impact: dict | None = None,
) -> None:
    session.add(
        AppointmentChangeLog(
            appointment_id=appointment.id,
            occurred_at=now(),
            actor=actor,
            reason_code=reason_code,
            from_state=from_state,
            to_state=to_state,
            from_starts_at=from_starts_at,
            to_starts_at=to_starts_at,
            impact_json=impact or {},
        )
    )


def _guard_version(appointment: Appointment, version: int) -> None:
    """Concorrência otimista. Quem chegou com versão velha não sobrescreve em silêncio."""
    if appointment.version != version:
        raise Conflict(
            ERR_YARD_APPOINTMENT_STALE,
            reference=appointment.reference,
            current_version=appointment.version,
            sent_version=version,
        )


async def _check_shift_open(session: AsyncSession, plant_id: UUID, start: datetime, end: datetime):
    """Turno fechado e parada de planta fecham a janela. Sem calendário, opera 24×7."""
    stoppage = (
        await session.execute(
            select(PlantStoppage).where(
                PlantStoppage.plant_id == plant_id,
                text("period && tstzrange(:s, :e)").bindparams(s=start, e=end),
            )
        )
    ).scalars().first()
    if stoppage is not None:
        raise Conflict(ERR_YARD_PLANT_STOPPAGE, reason=stoppage.reason_code)

    shifts = (
        await session.execute(
            select(ShiftCalendar).where(
                ShiftCalendar.plant_id == plant_id, ShiftCalendar.weekday == start.weekday()
            )
        )
    ).scalars().all()
    if not shifts:
        return
    if not any(s.starts_time <= start.time() and end.time() <= s.ends_time for s in shifts):
        raise Conflict(ERR_YARD_SHIFT_CLOSED, weekday=start.weekday())


async def _resource_remaining(
    session: AsyncSession, resource_id: UUID, start: datetime, end: datetime
) -> int:
    resource = await _one(
        session, select(Resource).where(Resource.id == resource_id), entity="resource"
    )
    used = (
        await session.execute(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.resource_id == resource_id,
                Appointment.state.in_(ACTIVE_STATES),
                Appointment.starts_at < end,
                Appointment.ends_at > start,
            )
        )
    ).scalar_one()
    return resource.capacity - used


async def _apply_priority(session: AsyncSession, appointment: Appointment, context: dict) -> None:
    """Primeira regra ativa cujo `match_json` esteja contido no contexto vence."""
    rules = (
        await session.execute(
            select(PriorityRule).where(PriorityRule.active.is_(True)).order_by(PriorityRule.rank)
        )
    ).scalars().all()
    for rule in rules:
        if all(context.get(key) == value for key, value in rule.match_json.items()):
            appointment.priority_code = rule.code
            appointment.priority_rank = rule.rank
            return
    appointment.priority_code = None
    appointment.priority_rank = 999


async def create(session: AsyncSession, data: AppointmentIn) -> Appointment:
    plate = data.plate.strip().upper().replace("-", "")
    vehicle = await _one(
        session, select(Vehicle).where(Vehicle.plate == plate), entity="vehicle", plate=plate
    )
    dock = await _one(
        session, select(Dock).where(Dock.code == data.dock_code), entity="dock", code=data.dock_code
    )
    operation = await _one(
        session,
        select(OperationType).where(OperationType.code == data.operation_type_code),
        entity="operation_type",
        code=data.operation_type_code,
    )
    plant_id = await _plant_id(session)
    await _check_shift_open(session, plant_id, data.starts_at, data.ends_at)

    driver_id = None
    if data.driver_document:
        driver = await _one(
            session,
            select(Driver).where(Driver.document == data.driver_document),
            entity="driver",
            document=data.driver_document,
        )
        driver_id = driver.id
    product_id = None
    hazardous = False
    if data.product_sku:
        product = await _one(
            session,
            select(Product).where(Product.sku == data.product_sku),
            entity="product",
            sku=data.product_sku,
        )
        product_id = product.id
        hazardous = product.hazardous
    resource_id = None
    if data.resource_code:
        resource = await _one(
            session,
            select(Resource).where(Resource.code == data.resource_code),
            entity="resource",
            code=data.resource_code,
        )
        resource_id = resource.id

    appointment = Appointment(
        plant_id=plant_id,
        reference=await _reference(session),
        state="requested",
        dock_id=dock.id,
        vehicle_id=vehicle.id,
        driver_id=driver_id,
        carrier_id=vehicle.carrier_id,
        product_id=product_id,
        operation_type_id=operation.id,
        resource_id=resource_id,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        channel=data.channel,
        created_by=data.actor,
        version=1,
    )
    await _apply_priority(
        session,
        appointment,
        {
            "operation_type": operation.code,
            "direction": operation.direction,
            "hazardous": hazardous,
            "channel": data.channel,
        },
    )
    session.add(appointment)
    await session.flush()
    await _log(
        session,
        appointment,
        actor=data.actor,
        reason_code=None,
        from_state=None,
        to_state="requested",
        to_starts_at=data.starts_at,
    )
    await session.commit()
    await hub.publish("yard.appointment.requested", {"reference": appointment.reference})
    return appointment


async def confirm(session: AsyncSession, appointment_id: UUID, data: ConfirmIn) -> Appointment:
    appointment = await _get(session, appointment_id)
    _guard_version(appointment, data.version)
    if appointment.state not in ("draft", "requested", "rescheduled"):
        raise Conflict(
            ERR_YARD_INVALID_TRANSITION, from_state=appointment.state, to_state="confirmed"
        )

    if appointment.resource_id:
        remaining = await _resource_remaining(
            session, appointment.resource_id, appointment.starts_at, appointment.ends_at
        )
        if remaining <= 0:
            raise Conflict(ERR_YARD_RESOURCE_EXHAUSTED, reference=appointment.reference)

    slot = await _reserve_slot(session, appointment, data.slot_code)
    previous = appointment.state
    appointment.state = "confirmed"
    appointment.version += 1
    appointment.slot_id = slot.id if slot else None
    await _log(
        session,
        appointment,
        actor=data.actor,
        reason_code=None,
        from_state=previous,
        to_state="confirmed",
        impact={"slot": slot.code if slot else None},
    )
    reference = appointment.reference
    try:
        await session.commit()
    except IntegrityError as exc:
        session.expunge_all()
        await session.rollback()
        raise _translate(exc, reference) from exc
    await hub.publish("yard.appointment.confirmed", {"reference": reference})
    return appointment


async def _reserve_slot(
    session: AsyncSession, appointment: Appointment, slot_code: str | None
) -> Slot | None:
    """Reserva de vaga na aprovação; liberação automática no gate-out (Fatia 1 fecha o ciclo)."""
    operation = await _one(
        session,
        select(OperationType).where(OperationType.id == appointment.operation_type_id),
        entity="operation_type",
    )
    if not operation.requires_dock and slot_code is None:
        return None

    if slot_code:
        slot = await _one(
            session, select(Slot).where(Slot.code == slot_code), entity="slot", code=slot_code
        )
    else:
        slot = (
            await session.execute(
                select(Slot)
                .outerjoin(
                    SlotReservation,
                    (SlotReservation.slot_id == Slot.id)
                    & (SlotReservation.state == "active")
                    & (SlotReservation.starts_at < appointment.ends_at)
                    & (SlotReservation.ends_at > appointment.starts_at),
                )
                .outerjoin(
                    SlotOccupancy,
                    (SlotOccupancy.slot_id == Slot.id) & (SlotOccupancy.ended_at.is_(None)),
                )
                .where(
                    Slot.status == "available",
                    SlotReservation.id.is_(None),
                    SlotOccupancy.id.is_(None),
                )
                .order_by(Slot.code)
                .limit(1)
            )
        ).scalars().first()
        if slot is None:
            raise Conflict(ERR_YARD_SLOT_OCCUPIED, slot="*")

    session.add(
        SlotReservation(
            slot_id=slot.id,
            appointment_id=appointment.id,
            vehicle_id=appointment.vehicle_id,
            state="active",
            # A vaga fica reservada da chegada prevista (janela − 30min) até o fim da janela.
            starts_at=appointment.starts_at - timedelta(minutes=30),
            ends_at=appointment.ends_at,
        )
    )
    return slot


async def reschedule(session: AsyncSession, appointment_id: UUID, data: RescheduleIn):
    appointment = await _get(session, appointment_id)
    _guard_version(appointment, data.version)
    if appointment.state in ("completed", "cancelled", "no_show"):
        raise Conflict(
            ERR_YARD_INVALID_TRANSITION, from_state=appointment.state, to_state="rescheduled"
        )

    impact = await compute_impact(
        session, appointment, data.starts_at, data.ends_at, data.dock_code
    )
    previous_start = appointment.starts_at
    previous_state = appointment.state
    if data.dock_code:
        dock = await _one(
            session,
            select(Dock).where(Dock.code == data.dock_code),
            entity="dock",
            code=data.dock_code,
        )
        appointment.dock_id = dock.id
    await _check_shift_open(session, appointment.plant_id, data.starts_at, data.ends_at)
    appointment.starts_at = data.starts_at
    appointment.ends_at = data.ends_at
    appointment.version += 1
    await _log(
        session,
        appointment,
        actor=data.actor,
        reason_code=data.reason_code,
        from_state=previous_state,
        to_state="rescheduled",
        from_starts_at=previous_start,
        to_starts_at=data.starts_at,
        impact=impact.model_dump(),
    )
    reference = appointment.reference
    try:
        await session.commit()
    except IntegrityError as exc:
        session.expunge_all()
        await session.rollback()
        raise _translate(exc, reference) from exc
    await hub.publish("yard.appointment.rescheduled", {"reference": reference})
    return appointment


async def cancel(session: AsyncSession, appointment_id: UUID, data: CancelIn) -> Appointment:
    appointment = await _get(session, appointment_id)
    _guard_version(appointment, data.version)
    previous = appointment.state
    appointment.state = "cancelled"
    appointment.version += 1
    await _release_reservations(session, appointment.id)
    await _log(
        session,
        appointment,
        actor=data.actor,
        reason_code=data.reason_code,
        from_state=previous,
        to_state="cancelled",
    )
    await session.commit()
    await hub.publish("yard.appointment.cancelled", {"reference": appointment.reference})
    return appointment


async def mark_no_show(session: AsyncSession, appointment_id: UUID, actor: str | None):
    appointment = await _get(session, appointment_id)
    previous = appointment.state
    appointment.state = "no_show"
    appointment.version += 1
    await _release_reservations(session, appointment.id)
    await _log(
        session,
        appointment,
        actor=actor,
        reason_code="NO_SHOW",
        from_state=previous,
        to_state="no_show",
    )
    await session.commit()
    return appointment


async def _release_reservations(session: AsyncSession, appointment_id: UUID) -> None:
    reservations = (
        await session.execute(
            select(SlotReservation).where(
                SlotReservation.appointment_id == appointment_id,
                SlotReservation.state == "active",
            )
        )
    ).scalars().all()
    for reservation in reservations:
        reservation.state = "released"


async def compute_impact(
    session: AsyncSession,
    appointment: Appointment,
    starts_at: datetime,
    ends_at: datetime,
    dock_code: str | None = None,
) -> ImpactOut:
    """Quantos agendamentos essa mudança desloca e quantos minutos de atraso projeta."""
    dock_id = appointment.dock_id
    if dock_code:
        dock = await _one(
            session, select(Dock).where(Dock.code == dock_code), entity="dock", code=dock_code
        )
        dock_id = dock.id

    conflicting = (
        await session.execute(
            select(Appointment).where(
                Appointment.dock_id == dock_id,
                Appointment.id != appointment.id,
                Appointment.state.in_(ACTIVE_STATES),
                Appointment.starts_at < ends_at,
                Appointment.ends_at > starts_at,
            )
        )
    ).scalars().all()

    delayed = 0
    for other in conflicting:
        overlap = min(ends_at, other.ends_at) - max(starts_at, other.starts_at)
        delayed += max(0, int(overlap.total_seconds() // 60))

    return ImpactOut(
        displaced_appointments=len(conflicting),
        delayed_minutes=delayed,
        conflicting_references=[a.reference for a in conflicting],
    )


async def link_visit(session: AsyncSession, appointment_id: UUID, visit_id: UUID) -> None:
    """Gate-in casa a visita com o agendamento e consome a reserva de vaga."""
    appointment = await _get(session, appointment_id)
    appointment.visit_id = visit_id
    appointment.state = "checked_in"
    appointment.version += 1
    reservations = (
        await session.execute(
            select(SlotReservation).where(
                SlotReservation.appointment_id == appointment_id,
                SlotReservation.state == "active",
            )
        )
    ).scalars().all()
    for reservation in reservations:
        reservation.state = "consumed"
    await _log(
        session,
        appointment,
        actor="gate",
        reason_code=None,
        from_state="confirmed",
        to_state="checked_in",
    )


async def _get(session: AsyncSession, appointment_id: UUID) -> Appointment:
    return await _one(
        session,
        select(Appointment).where(Appointment.id == appointment_id),
        entity="appointment",
        id=str(appointment_id),
    )


def _translate(exc: IntegrityError, reference: str) -> Conflict:
    detail = str(getattr(exc, "orig", exc))
    if "ex_appointment_dock" in detail:
        return Conflict(ERR_YARD_DOCK_WINDOW_TAKEN, reference=reference)
    if "ex_appointment_vehicle" in detail:
        return Conflict(ERR_YARD_DOCK_WINDOW_TAKEN, reference=reference, scope="vehicle")
    if "ex_slot_reservation" in detail:
        return Conflict(ERR_YARD_SLOT_OCCUPIED, reference=reference)
    if "ERR_YARD_PLANT_STOPPAGE" in detail:
        return Conflict(ERR_YARD_PLANT_STOPPAGE, reference=reference)
    if "ERR_YARD_APPOINTMENT_STALE" in detail:
        return Conflict(ERR_YARD_APPOINTMENT_STALE, reference=reference)
    return Conflict(ERR_YARD_DOCK_WINDOW_TAKEN, reference=reference)
