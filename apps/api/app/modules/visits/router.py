from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires
from app.core.errors import ERR_NOT_FOUND, NotFound
from app.domain.enums import OPEN_STATES, VisitState
from app.modules.catalog.models import Carrier, Driver, OperationType, Product, Vehicle
from app.modules.visits import service
from app.modules.visits.models import Visit, VisitEvent
from app.modules.visits.schemas import (
    DockAssignIn,
    GateInIn,
    GateOutIn,
    RejectVisitIn,
    SlotAssignIn,
    VisitDetailOut,
    VisitEventOut,
    VisitOut,
)
from app.modules.yard.models import Dock, Slot

router = APIRouter(
    prefix="/visits",
    tags=["visits"],
    dependencies=[Depends(requires(Role.GATE, Role.CONTROLLER, Role.SUPERVISOR))],
)


def _projection() -> Select:
    return (
        select(
            Visit,
            Vehicle.plate,
            Vehicle.trailer_plate,
            Driver.full_name,
            Carrier.name.label("carrier_name"),
            Product.name.label("product_name"),
            OperationType.code.label("operation_type_code"),
            OperationType.direction.label("operation_direction"),
            OperationType.target_dwell_minutes,
            Slot.code.label("slot_code"),
            Dock.code.label("dock_code"),
        )
        .join(Vehicle, Vehicle.id == Visit.vehicle_id)
        .join(Driver, Driver.id == Visit.driver_id)
        .join(OperationType, OperationType.id == Visit.operation_type_id)
        .outerjoin(Carrier, Carrier.id == Visit.carrier_id)
        .outerjoin(Product, Product.id == Visit.product_id)
        .outerjoin(Slot, Slot.id == Visit.current_slot_id)
        .outerjoin(Dock, Dock.id == Visit.current_dock_id)
    )


def _to_out(row) -> VisitOut:
    visit: Visit = row[0]
    return VisitOut(
        id=visit.id,
        reference=visit.reference,
        state=VisitState(visit.state),
        plate=row.plate,
        trailer_plate=row.trailer_plate,
        driver_name=row.full_name,
        carrier_name=row.carrier_name,
        product_name=row.product_name,
        operation_type_code=row.operation_type_code,
        operation_direction=row.operation_direction,
        slot_code=row.slot_code,
        dock_code=row.dock_code,
        arrived_at=visit.arrived_at,
        gate_in_at=visit.gate_in_at,
        gate_out_at=visit.gate_out_at,
        dwell_seconds=service.dwell_seconds(visit),
        target_dwell_minutes=row.target_dwell_minutes,
        blocked_reason_code=visit.blocked_reason_code,
        document_number=visit.document_number,
    )


@router.get("", response_model=list[VisitOut])
async def list_visits(
    session: AsyncSession = Depends(get_session),
    state: list[VisitState] | None = Query(default=None),
    only_open: bool = False,
    search: str | None = None,
    limit: int = Query(default=200, le=1000),
) -> list[VisitOut]:
    stmt = _projection()
    if only_open:
        stmt = stmt.where(Visit.state.in_([s.value for s in OPEN_STATES]))
    if state:
        stmt = stmt.where(Visit.state.in_([s.value for s in state]))
    if search:
        term = f"%{search.strip().upper()}%"
        stmt = stmt.where(Vehicle.plate.ilike(term) | Visit.reference.ilike(term))
    stmt = stmt.order_by(desc(Visit.arrived_at)).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [_to_out(r) for r in rows]


@router.get("/{visit_id}", response_model=VisitDetailOut)
async def get_visit(
    visit_id: UUID, session: AsyncSession = Depends(get_session)
) -> VisitDetailOut:
    row = (await session.execute(_projection().where(Visit.id == visit_id))).first()
    if row is None:
        raise NotFound(ERR_NOT_FOUND, entity="visit", id=str(visit_id))
    events = (
        await session.execute(
            select(VisitEvent)
            .where(VisitEvent.visit_id == visit_id)
            .order_by(desc(VisitEvent.occurred_at))
        )
    ).scalars()
    base = _to_out(row)
    return VisitDetailOut(
        **base.model_dump(), events=[VisitEventOut.model_validate(e) for e in events]
    )


async def _reload(session: AsyncSession, visit_id: UUID) -> VisitOut:
    row = (await session.execute(_projection().where(Visit.id == visit_id))).first()
    return _to_out(row)


@router.post("/gate-in", response_model=VisitOut, status_code=201)
async def gate_in(data: GateInIn, session: AsyncSession = Depends(get_session)) -> VisitOut:
    visit = await service.gate_in(session, data)
    return await _reload(session, visit.id)


@router.post("/{visit_id}/slot", response_model=VisitOut)
async def assign_slot(
    visit_id: UUID, data: SlotAssignIn, session: AsyncSession = Depends(get_session)
) -> VisitOut:
    await service.assign_slot(session, visit_id, data)
    return await _reload(session, visit_id)


@router.post("/{visit_id}/dock", response_model=VisitOut)
async def assign_dock(
    visit_id: UUID, data: DockAssignIn, session: AsyncSession = Depends(get_session)
) -> VisitOut:
    await service.assign_dock(session, visit_id, data)
    return await _reload(session, visit_id)


@router.post("/{visit_id}/reject", response_model=VisitOut)
async def reject(
    visit_id: UUID, data: RejectVisitIn, session: AsyncSession = Depends(get_session)
) -> VisitOut:
    """Recusa a entrada: o veículo sai da fila e a vaga reservada volta para o pool."""
    await service.reject(session, visit_id, data)
    return await _reload(session, visit_id)


@router.post("/{visit_id}/gate-out", response_model=VisitOut)
async def gate_out(
    visit_id: UUID, data: GateOutIn, session: AsyncSession = Depends(get_session)
) -> VisitOut:
    await service.gate_out(session, visit_id, data)
    return await _reload(session, visit_id)
