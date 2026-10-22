"""Regras do núcleo de pátio. Toda mudança de estado passa por aqui e deixa evento."""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_NOT_FOUND,
    ERR_YARD_APPOINTMENT_WINDOW_MISSED,
    ERR_YARD_DRIVER_LICENSE_EXPIRED,
    ERR_YARD_EXIT_BLOCKED_BY_PENDENCY,
    ERR_YARD_INVALID_TRANSITION,
    ERR_YARD_SLOT_BLOCKED,
    ERR_YARD_SLOT_OCCUPIED,
    ERR_YARD_VEHICLE_ALREADY_IN_YARD,
    Conflict,
    NotFound,
)
from app.core.events import hub
from app.domain.enums import OPEN_STATES, TRANSITIONS, EventSource, EventType, VisitState
from app.modules.catalog.models import Driver, OperationType, Product, Vehicle
from app.modules.gate import service as gate_service
from app.modules.moves import service as moves_service
from app.modules.scheduling import service as scheduling_service
from app.modules.scheduling.models import Appointment, SlotReservation
from app.modules.visits.models import Visit, VisitEvent
from app.modules.visits.schemas import (
    DockAssignIn,
    GateInIn,
    GateOutIn,
    RejectVisitIn,
    SlotAssignIn,
)
from app.modules.yard.models import Dock, Gate, Slot, SlotOccupancy


def now() -> datetime:
    return datetime.now(timezone.utc)


async def _one(session: AsyncSession, stmt, entity: str, **params: Any):
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, **params)
    return obj


async def _plant_id(session: AsyncSession) -> UUID:
    """Planta padrão da instância: a de `YARD_PLANT_CODE`, senão a primeira cadastrada."""
    from app.core.config import settings

    return (
        await session.execute(
            text(
                "SELECT id FROM plant ORDER BY (code = :code) DESC, active DESC, code LIMIT 1"
            ),
            {"code": settings.plant_code},
        )
    ).scalar_one()


async def _next_reference(session: AsyncSession) -> str:
    seq = (await session.execute(text("SELECT nextval('visit_reference_seq')"))).scalar_one()
    return f"YRD-{date.today().year}-{seq:06d}"


async def _record(
    session: AsyncSession,
    visit: Visit,
    event_type: EventType,
    *,
    source: EventSource,
    actor: str | None,
    from_state: str | None = None,
    to_state: str | None = None,
    payload: dict | None = None,
) -> None:
    session.add(
        VisitEvent(
            occurred_at=now(),
            visit_id=visit.id,
            event_type=event_type.value,
            source=source.value,
            actor=actor,
            from_state=from_state,
            to_state=to_state,
            payload=payload or {},
        )
    )


def _transition(visit: Visit, target: VisitState) -> str:
    current = VisitState(visit.state)
    if target not in TRANSITIONS[current]:
        raise Conflict(ERR_YARD_INVALID_TRANSITION, from_state=current.value, to_state=target.value)
    visit.state = target.value
    return current.value


async def _publish(topic: str, visit: Visit, **extra: Any) -> None:
    await hub.publish(
        topic,
        {"visit_id": str(visit.id), "reference": visit.reference, "state": visit.state, **extra},
    )


async def gate_in(session: AsyncSession, data: GateInIn) -> Visit:
    plate = data.plate.strip().upper().replace("-", "")
    vehicle: Vehicle = await _one(
        session,
        select(Vehicle).where(Vehicle.plate == plate),
        entity="vehicle",
        plate=plate,
    )
    driver: Driver = await _one(
        session,
        select(Driver).where(Driver.document == data.driver_document.strip()),
        entity="driver",
        document=data.driver_document,
    )
    operation: OperationType = await _one(
        session,
        select(OperationType).where(OperationType.code == data.operation_type_code),
        entity="operation_type",
        code=data.operation_type_code,
    )

    # ASSUNÇÃO: CNH vencida bloqueia a entrada; liberação excepcional é decisão de supervisor
    # e entra como override auditado na Fatia 4.
    if driver.license_expires_on and driver.license_expires_on < date.today():
        raise Conflict(
            ERR_YARD_DRIVER_LICENSE_EXPIRED,
            driver=driver.full_name,
            expired_on=driver.license_expires_on.isoformat(),
        )

    open_visit = (
        await session.execute(
            select(Visit).where(
                Visit.vehicle_id == vehicle.id,
                Visit.state.in_([s.value for s in OPEN_STATES]),
            )
        )
    ).scalar_one_or_none()
    if open_visit is not None:
        raise Conflict(
            ERR_YARD_VEHICLE_ALREADY_IN_YARD, plate=plate, reference=open_visit.reference
        )

    product_id = None
    if data.product_sku:
        product = await _one(
            session,
            select(Product).where(Product.sku == data.product_sku),
            entity="product",
            sku=data.product_sku,
        )
        product_id = product.id

    gate_id = None
    gate_plant_id = None
    if data.gate_code:
        gate = await _one(
            session,
            select(Gate).where(Gate.code == data.gate_code),
            entity="gate",
            code=data.gate_code,
        )
        gate_id = gate.id
        # Com vários pátios, quem diz onde a visita acontece é a guarita de entrada.
        gate_plant_id = gate.plant_id

    appointment = None
    if data.appointment_reference:
        appointment = await _one(
            session,
            select(Appointment).where(Appointment.reference == data.appointment_reference),
            entity="appointment",
            reference=data.appointment_reference,
        )
        # ASSUNÇÃO: tolerância de 2h antes e 4h depois da janela; fora disso é exceção
        # de triagem e precisa de decisão humana (override entra na Fatia 4).
        if not (
            appointment.starts_at - timedelta(hours=2)
            <= now()
            <= appointment.ends_at + timedelta(hours=4)
        ):
            raise Conflict(
                ERR_YARD_APPOINTMENT_WINDOW_MISSED,
                reference=appointment.reference,
                starts_at=appointment.starts_at.isoformat(),
            )

    visit = Visit(
        plant_id=gate_plant_id or await _plant_id(session),
        reference=await _next_reference(session),
        state=VisitState.AT_GATE_IN.value,
        vehicle_id=vehicle.id,
        driver_id=driver.id,
        carrier_id=vehicle.carrier_id or driver.carrier_id,
        product_id=product_id,
        operation_type_id=operation.id,
        gate_in_id=gate_id,
        arrived_at=now(),
        document_number=data.document_number,
        seal_number=data.seal_number,
        notes=data.notes,
        appointment_id=appointment.id if appointment else None,
    )
    session.add(visit)
    await session.flush()
    if appointment is not None:
        await scheduling_service.link_visit(session, appointment.id, visit.id)
    await _record(
        session,
        visit,
        EventType.GATE_IN,
        source=data.source,
        actor=data.actor,
        to_state=visit.state,
        payload={"plate": plate, "operation_type": operation.code},
    )
    await session.commit()
    await _publish("yard.visit.gate_in", visit, plate=plate)
    return visit


async def assign_slot(session: AsyncSession, visit_id: UUID, data: SlotAssignIn) -> Visit:
    """Aloca vaga e libera o veículo para o pátio (at_gate_in → in_yard).

    Sem `slot_code`, escolhe a primeira vaga livre da zona compatível — alocação automática
    ingênua de propósito: a otimização entra na Fatia 7, com humano confirmando.
    """
    visit = await _get(session, visit_id)

    if data.slot_code:
        slot: Slot = await _one(
            session,
            select(Slot).where(Slot.code == data.slot_code),
            entity="slot",
            code=data.slot_code,
        )
        if slot.status != "available":
            raise Conflict(ERR_YARD_SLOT_BLOCKED, slot=slot.code, status=slot.status)
        busy = (
            await session.execute(
                select(SlotOccupancy.id).where(
                    SlotOccupancy.slot_id == slot.id, SlotOccupancy.ended_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if busy is not None:
            raise Conflict(ERR_YARD_SLOT_OCCUPIED, slot=slot.code)
    else:
        # Vaga reservada na confirmação do agendamento tem precedência sobre a alocação
        # automática: reservar e depois ignorar a reserva seria teatro.
        slot = None
        if visit.appointment_id:
            slot = (
                await session.execute(
                    select(Slot)
                    .join(SlotReservation, SlotReservation.slot_id == Slot.id)
                    .where(
                        SlotReservation.appointment_id == visit.appointment_id,
                        SlotReservation.state.in_(("active", "consumed")),
                        Slot.status == "available",
                    )
                    .limit(1)
                )
            ).scalars().first()
        # Vaga reservada para OUTRO agendamento na janela de agora está fora do sorteio:
        # reservar e deixar qualquer um estacionar em cima seria reserva de mentira.
        reserved_by_others = (
            select(SlotReservation.slot_id)
            .where(
                SlotReservation.state == "active",
                SlotReservation.starts_at <= now(),
                SlotReservation.ends_at > now(),
            )
        )
        if visit.appointment_id:
            reserved_by_others = reserved_by_others.where(
                SlotReservation.appointment_id != visit.appointment_id
            )
        slot = slot or (
            await session.execute(
                select(Slot)
                .outerjoin(
                    SlotOccupancy,
                    (SlotOccupancy.slot_id == Slot.id) & (SlotOccupancy.ended_at.is_(None)),
                )
                .where(
                    Slot.plant_id == visit.plant_id,
                    Slot.status == "available",
                    SlotOccupancy.id.is_(None),
                    Slot.id.notin_(reserved_by_others),
                )
                .order_by(Slot.code)
                .limit(1)
            )
        ).scalar_one_or_none()
        if slot is None:
            raise Conflict(ERR_YARD_SLOT_OCCUPIED, slot="*")

    previous = visit.state
    if VisitState(visit.state) is VisitState.AT_GATE_IN:
        # Triagem só libera com checklist limpo: item bloqueante reprovado segura aqui,
        # antes de qualquer comando de cancela.
        await gate_service.ensure_checklist_ok(session, visit.id)
        _transition(visit, VisitState.IN_YARD)
        visit.gate_in_at = now()
    elif VisitState(visit.state) in (VisitState.IN_YARD, VisitState.AT_DOCK):
        await _release_slot(session, visit)
        if VisitState(visit.state) is VisitState.AT_DOCK:
            await _release_dock(session, visit)
            _transition(visit, VisitState.IN_YARD)
    else:
        raise Conflict(
            ERR_YARD_INVALID_TRANSITION, from_state=visit.state, to_state=VisitState.IN_YARD.value
        )

    session.add(
        SlotOccupancy(
            slot_id=slot.id, visit_id=visit.id, vehicle_id=visit.vehicle_id, started_at=now()
        )
    )
    visit.current_slot_id = slot.id
    await _record(
        session,
        visit,
        EventType.SLOT_ASSIGNED,
        source=data.source,
        actor=data.actor,
        from_state=previous,
        to_state=visit.state,
        payload={"slot": slot.code, "auto": data.slot_code is None},
    )
    # Guardado antes do commit: depois de um rollback o objeto está expirado e ler
    # `slot.code` dispararia IO lazy fora do contexto async.
    slot_code = slot.code
    try:
        await session.commit()
    except IntegrityError as exc:  # EXCLUDE do banco teve a última palavra (corrida)
        session.expunge_all()  # solta o estado ORM antes do rollback: nada de IO lazy depois
        await session.rollback()
        raise Conflict(ERR_YARD_SLOT_OCCUPIED, slot=slot_code) from exc
    await _publish("yard.slot.assigned", visit, slot=slot_code)
    return visit


async def assign_dock(session: AsyncSession, visit_id: UUID, data: DockAssignIn) -> Visit:
    visit = await _get(session, visit_id)
    dock: Dock = await _one(
        session, select(Dock).where(Dock.code == data.dock_code), entity="dock", code=data.dock_code
    )
    if dock.status != "available":
        raise Conflict(ERR_YARD_SLOT_BLOCKED, dock=dock.code, status=dock.status)

    previous = _transition(visit, VisitState.AT_DOCK)
    await _release_slot(session, visit)
    visit.current_dock_id = dock.id
    visit.dock_in_at = now()
    dock.status = "occupied"
    await _record(
        session,
        visit,
        EventType.DOCK_ASSIGNED,
        source=data.source,
        actor=data.actor,
        from_state=previous,
        to_state=visit.state,
        payload={"dock": dock.code},
    )
    await session.commit()
    await _publish("yard.dock.assigned", visit, dock=dock.code)
    return visit


async def gate_out(session: AsyncSession, visit_id: UUID, data: GateOutIn) -> Visit:
    visit = await _get(session, visit_id)
    if visit.blocked_reason_code:
        raise Conflict(ERR_YARD_EXIT_BLOCKED_BY_PENDENCY, reason=visit.blocked_reason_code)
    # Pendência de qualidade/fiscal aberta segura o veículo, mesmo sem marca na visita.
    await moves_service.ensure_no_open_hold(session, visit_id)

    # Ordem importa: libera posição e carimba a saída ANTES de mudar o estado.
    # `ck_visit_departed_has_timestamp` recusa 'departed' sem gate_out_at, e o autoflush
    # de qualquer consulta no meio levaria o estado ao banco antes do carimbo.
    await _release_slot(session, visit)
    await _release_dock(session, visit)
    if data.gate_code:
        gate = await _one(
            session,
            select(Gate).where(Gate.code == data.gate_code),
            entity="gate",
            code=data.gate_code,
        )
        visit.gate_out_id = gate.id
    visit.gate_out_at = now()

    if VisitState(visit.state) in (VisitState.IN_YARD, VisitState.AT_DOCK):
        _transition(visit, VisitState.AT_GATE_OUT)
    previous = _transition(visit, VisitState.DEPARTED)
    await _record(
        session,
        visit,
        EventType.GATE_OUT,
        source=data.source,
        actor=data.actor,
        from_state=previous,
        to_state=visit.state,
        payload={"dwell_seconds": dwell_seconds(visit)},
    )
    await session.commit()
    await _publish("yard.visit.gate_out", visit)
    return visit


async def reject(session: AsyncSession, visit_id: UUID, data: "RejectVisitIn") -> Visit:
    """Recusa a entrada na triagem.

    O spec prevê o estado `rejected` desde a Fatia 1, mas faltava o caminho para chegar
    nele: sem isso, veículo barrado na guarita ficava eternamente `at_gate_in`, contando
    fila e dwell que não existem. Recusar é decisão registrada, com motivo e autor.
    """
    visit = await _get(session, visit_id)
    previous = _transition(visit, VisitState.REJECTED)
    visit.blocked_reason_code = None
    await _release_slot(session, visit)
    await _release_dock(session, visit)

    # A reserva do agendamento volta para o pool: a doca não fica esperando quem não entra.
    reservations = (
        await session.execute(
            select(SlotReservation).where(
                SlotReservation.appointment_id == visit.appointment_id,
                SlotReservation.state == "active",
            )
        )
    ).scalars().all() if visit.appointment_id else []
    for reservation in reservations:
        reservation.state = "released"

    await _record(
        session,
        visit,
        EventType.REJECTED,
        source=data.source,
        actor=data.actor,
        from_state=previous,
        to_state=visit.state,
        payload={"reason_code": data.reason_code, "note": data.note},
    )
    await session.commit()
    await _publish("yard.visit.rejected", visit, reason=data.reason_code)
    return visit


async def _get(session: AsyncSession, visit_id: UUID) -> Visit:
    return await _one(
        session, select(Visit).where(Visit.id == visit_id), entity="visit", id=str(visit_id)
    )


async def _release_slot(session: AsyncSession, visit: Visit) -> None:
    occupancy = (
        await session.execute(
            select(SlotOccupancy).where(
                SlotOccupancy.visit_id == visit.id, SlotOccupancy.ended_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if occupancy is not None:
        occupancy.ended_at = now()
    visit.current_slot_id = None


async def _release_dock(session: AsyncSession, visit: Visit) -> None:
    """Libera a doca: status, carimbo e — o que faltava — a ocupação em `dock_visit`.

    Sem fechar a ocupação, a doca continuava presa no EXCLUDE de período: o veículo saía
    do pátio e a doca nunca mais aceitava outro, sem nenhuma tela mostrando o porquê.
    """
    from app.modules.moves.models import DockVisit

    open_dock_visits = (
        await session.execute(
            select(DockVisit).where(
                DockVisit.visit_id == visit.id, DockVisit.released_at.is_(None)
            )
        )
    ).scalars().all()
    # Um só instante: dois `now()` seguidos deixavam finished_at microssegundos depois de
    # released_at, e o ck_dock_stage_order recusava a saída.
    released_at = now()
    for dock_visit in open_dock_visits:
        dock_visit.released_at = released_at
        dock_visit.state = "released"
        if dock_visit.finished_at is None:
            dock_visit.finished_at = released_at

    if visit.current_dock_id is None:
        return
    dock = (
        await session.execute(select(Dock).where(Dock.id == visit.current_dock_id))
    ).scalar_one_or_none()
    if dock is not None:
        dock.status = "available"
    visit.dock_out_at = now()
    visit.current_dock_id = None


def dwell_seconds(visit: Visit) -> int:
    """Dwell total: da chegada à guarita até a saída (ou até agora, se ainda dentro)."""
    end = visit.gate_out_at or now()
    return max(0, int((end - visit.arrived_at).total_seconds()))
