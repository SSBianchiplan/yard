from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires
from app.modules.catalog.models import Vehicle
from app.modules.visits.models import Visit
from app.modules.visits.service import dwell_seconds
from app.modules.yard.models import Dock, Gate, Scale, Slot, SlotOccupancy, Zone

router = APIRouter(
    prefix="/yard",
    tags=["yard"],
    dependencies=[Depends(requires(Role.GATE, Role.CONTROLLER, Role.SPOTTER))],
)


class Box(BaseModel):
    id: UUID
    code: str
    x: float
    y: float
    width: float
    height: float


class ZoneOut(Box):
    kind: str
    color_token: str | None = None


class SlotOut(Box):
    zone_id: UUID
    kind: str
    status: str
    occupied: bool = False
    visit_id: UUID | None = None
    visit_reference: str | None = None
    plate: str | None = None
    since: datetime | None = None
    dwell_seconds: int | None = None


class DockOut(Box):
    direction: str
    status: str
    visit_id: UUID | None = None
    plate: str | None = None


class PointOut(BaseModel):
    id: UUID
    code: str
    x: float
    y: float
    direction: str | None = None


class MapOut(BaseModel):
    plant_code: str
    timezone: str
    generated_at: datetime
    zones: list[ZoneOut]
    slots: list[SlotOut]
    docks: list[DockOut]
    gates: list[PointOut]
    scales: list[PointOut]


@router.get("/map", response_model=MapOut)
async def yard_map(
    session: AsyncSession = Depends(get_session), plant: str | None = None
) -> MapOut:
    """Mapa de UM pátio: o pedido (`?plant=CODE`), senão o padrão da instância.

    Misturar a geometria de dois pátios no mesmo SVG sobrepõe vagas de plantas diferentes.
    """
    from app.core.config import settings
    from app.modules.catalog.models import Plant

    wanted = (plant or settings.plant_code).upper()
    current = (
        await session.execute(
            select(Plant).order_by((Plant.code == wanted).desc(), Plant.active.desc(), Plant.code)
        )
    ).scalars().first()
    plant_id = current.id if current else None

    async def rows(model):
        return (
            await session.execute(
                select(model).where(model.plant_id == plant_id).order_by(model.code)
            )
        ).scalars().all()

    zones = await rows(Zone)
    slots = await rows(Slot)
    docks = await rows(Dock)
    gates = await rows(Gate)
    scales = await rows(Scale)

    occupancy_rows = (
        await session.execute(
            select(SlotOccupancy, Visit, Vehicle.plate)
            .join(Visit, Visit.id == SlotOccupancy.visit_id)
            .join(Vehicle, Vehicle.id == SlotOccupancy.vehicle_id)
            .where(SlotOccupancy.ended_at.is_(None))
        )
    ).all()
    by_slot = {row[0].slot_id: row for row in occupancy_rows}

    dock_rows = (
        await session.execute(
            select(Visit, Vehicle.plate)
            .join(Vehicle, Vehicle.id == Visit.vehicle_id)
            .where(Visit.current_dock_id.is_not(None))
        )
    ).all()
    by_dock = {row[0].current_dock_id: row for row in dock_rows}

    return MapOut(
        plant_code=current.code if current else "",
        timezone=current.timezone if current else "UTC",
        generated_at=datetime.now(),
        zones=[
            ZoneOut(
                id=z.id,
                code=z.code,
                kind=z.kind,
                x=float(z.x),
                y=float(z.y),
                width=float(z.width),
                height=float(z.height),
                color_token=z.color_token,
            )
            for z in zones
        ],
        slots=[
            _slot_out(s, by_slot.get(s.id))
            for s in slots
        ],
        docks=[
            DockOut(
                id=d.id,
                code=d.code,
                x=float(d.x),
                y=float(d.y),
                width=float(d.width),
                height=float(d.height),
                direction=d.direction,
                status=d.status,
                visit_id=by_dock[d.id][0].id if d.id in by_dock else None,
                plate=by_dock[d.id].plate if d.id in by_dock else None,
            )
            for d in docks
        ],
        gates=[
            PointOut(id=g.id, code=g.code, x=float(g.x), y=float(g.y), direction=g.direction)
            for g in gates
        ],
        scales=[PointOut(id=s.id, code=s.code, x=float(s.x), y=float(s.y)) for s in scales],
    )


def _slot_out(slot: Slot, row) -> SlotOut:
    out = SlotOut(
        id=slot.id,
        code=slot.code,
        zone_id=slot.zone_id,
        kind=slot.kind,
        status=slot.status,
        x=float(slot.x),
        y=float(slot.y),
        width=float(slot.width),
        height=float(slot.height),
    )
    if row is not None:
        occupancy, visit, plate = row
        out.occupied = True
        out.visit_id = visit.id
        out.visit_reference = visit.reference
        out.plate = plate
        out.since = occupancy.started_at
        out.dwell_seconds = dwell_seconds(visit)
    return out


@router.get("/slots", response_model=list[SlotOut])
async def list_slots(
    session: AsyncSession = Depends(get_session), plant: str | None = None
) -> list[SlotOut]:
    return (await yard_map(session, plant)).slots


@router.get("/docks", response_model=list[DockOut])
async def list_docks(
    session: AsyncSession = Depends(get_session), plant: str | None = None
) -> list[DockOut]:
    return (await yard_map(session, plant)).docks
