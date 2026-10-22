"""Configuração de pátio: criar e editar planta, zonas, vagas, docas, guaritas e balanças.

Código de elemento é único no sistema inteiro (não só no pátio) — é por ele que guarita,
balança, manobra e agendamento acham a vaga ou a doca. Por isso o assistente prefixa os
códigos com o código do pátio: dois pátios com "DOCK-01" seriam uma doca ambígua em
toda a operação.

Apagar só vale para elemento sem histórico. Vaga que já teve caminhão tem trilha de
auditoria pendurada nela; nesse caso a resposta é `ERR_YARD_CONFIG_IN_USE` e a saída
é bloquear ou pôr em manutenção.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_NOT_FOUND, AppError, Conflict, NotFound
from app.modules.catalog.models import Plant
from app.modules.yard.models import Dock, Gate, Scale, Slot, Zone
from app.modules.yardconfig.schemas import LayoutTemplate, PlantOut, SlotGridIn

ERR_YARD_CODE_TAKEN = "ERR_YARD_CODE_TAKEN"
ERR_YARD_CONFIG_IN_USE = "ERR_YARD_CONFIG_IN_USE"
ERR_YARD_ZONE_OTHER_PLANT = "ERR_YARD_ZONE_OTHER_PLANT"

MODELS: dict[str, Any] = {
    "zone": Zone,
    "slot": Slot,
    "dock": Dock,
    "gate": Gate,
    "scale": Scale,
}


async def get_plant(session: AsyncSession, plant_id: UUID) -> Plant:
    plant = await session.get(Plant, plant_id)
    if plant is None:
        raise NotFound(ERR_NOT_FOUND, entity="plant", id=str(plant_id))
    return plant


async def plant_summaries(session: AsyncSession, plant_id: UUID | None = None) -> list[PlantOut]:
    from app.core.config import settings

    # o pátio padrão da instância primeiro: é o que o mapa mostra sem escolha explícita
    stmt = select(Plant).order_by(
        (Plant.code == settings.plant_code).desc(), Plant.active.desc(), Plant.code
    )
    if plant_id:
        stmt = stmt.where(Plant.id == plant_id)
    plants = (await session.execute(stmt)).scalars().all()
    counts: dict[str, dict[UUID, int]] = {}
    for name, model in MODELS.items():
        rows = (
            await session.execute(select(model.plant_id, func.count()).group_by(model.plant_id))
        ).all()
        counts[name] = {row[0]: row[1] for row in rows}
    return [
        PlantOut(
            id=p.id,
            code=p.code,
            name=p.name,
            timezone=p.timezone,
            segment=p.segment,
            city=p.city,
            description=p.description,
            active=p.active,
            zones=counts["zone"].get(p.id, 0),
            slots=counts["slot"].get(p.id, 0),
            docks=counts["dock"].get(p.id, 0),
            gates=counts["gate"].get(p.id, 0),
            scales=counts["scale"].get(p.id, 0),
        )
        for p in plants
    ]


async def _commit(session: AsyncSession, entity: str, code: str | None = None) -> None:
    await _guarded(session.commit(), session, entity, code)


async def _guarded(awaitable, session: AsyncSession, entity: str, code: str | None) -> Any:
    """Violação de unicidade/FK vira código traduzível; o resto sobe como está."""
    try:
        return await awaitable
    except IntegrityError as exc:
        await session.rollback()
        detail = str(getattr(exc, "orig", exc))
        if "unique" in detail.lower() or "duplicate" in detail.lower():
            raise Conflict(ERR_YARD_CODE_TAKEN, entity=entity, code=code or "") from exc
        if "foreign key" in detail.lower():
            raise Conflict(ERR_YARD_CONFIG_IN_USE, entity=entity, code=code or "") from exc
        raise


async def create_plant(
    session: AsyncSession, data: dict[str, Any], template: LayoutTemplate | None
) -> Plant:
    plant = Plant(id=uuid4(), **data)
    session.add(plant)
    await _guarded(session.flush(), session, "plant", data["code"])
    if template is not None:
        await _guarded(_generate_layout(session, plant, template), session, "plant", data["code"])
    await _commit(session, "plant", data["code"])
    return plant


async def update_plant(session: AsyncSession, plant_id: UUID, changes: dict[str, Any]) -> Plant:
    plant = await get_plant(session, plant_id)
    for key, value in changes.items():
        setattr(plant, key, value)
    await _commit(session, "plant", plant.code)
    return plant


async def _ensure_zone_in_plant(session: AsyncSession, zone_id: UUID | None, plant_id: UUID):
    if zone_id is None:
        return
    zone = await session.get(Zone, zone_id)
    if zone is None:
        raise NotFound(ERR_NOT_FOUND, entity="zone", id=str(zone_id))
    if zone.plant_id != plant_id:
        raise AppError(ERR_YARD_ZONE_OTHER_PLANT, zone=zone.code)


async def create_element(session: AsyncSession, entity: str, plant_id: UUID, data: dict[str, Any]):
    await get_plant(session, plant_id)
    await _ensure_zone_in_plant(session, data.get("zone_id"), plant_id)
    obj = MODELS[entity](id=uuid4(), plant_id=plant_id, **data)
    session.add(obj)
    await _commit(session, entity, data.get("code"))
    return obj


async def _get_element(session: AsyncSession, entity: str, element_id: UUID):
    obj = await session.get(MODELS[entity], element_id)
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, id=str(element_id))
    return obj


async def update_element(
    session: AsyncSession, entity: str, element_id: UUID, changes: dict[str, Any]
):
    obj = await _get_element(session, entity, element_id)
    if "zone_id" in changes:
        await _ensure_zone_in_plant(session, changes["zone_id"], obj.plant_id)
    for key, value in changes.items():
        setattr(obj, key, value)
    await _commit(session, entity, changes.get("code", obj.code))
    return obj


async def delete_element(session: AsyncSession, entity: str, element_id: UUID) -> None:
    obj = await _get_element(session, entity, element_id)
    code = obj.code
    await session.delete(obj)
    await _commit(session, entity, code)


async def generate_slots(session: AsyncSession, zone_id: UUID, grid: SlotGridIn) -> list[Slot]:
    zone = await session.get(Zone, zone_id)
    if zone is None:
        raise NotFound(ERR_NOT_FOUND, entity="zone", id=str(zone_id))
    rows = _grid_rows(zone, grid)
    if rows:
        await _guarded(session.execute(insert(Slot), rows), session, "slot", f"{grid.prefix}-*")
    await _commit(session, "slot", f"{grid.prefix}-*")
    ids = [row["id"] for row in rows]
    return list(
        (await session.execute(select(Slot).where(Slot.id.in_(ids)).order_by(Slot.code)))
        .scalars()
        .all()
    )


def _grid_rows(zone: Zone, grid: SlotGridIn) -> list[dict[str, Any]]:
    rows = []
    number = grid.start_number
    for r in range(grid.rows):
        for c in range(grid.cols):
            rows.append(
                {
                    "id": uuid4(),
                    "plant_id": zone.plant_id,
                    "zone_id": zone.id,
                    "code": f"{grid.prefix}-{number:02d}",
                    "kind": grid.kind or zone.kind,
                    "status": "available",
                    "length_m": 18,
                    "x": float(zone.x) + grid.margin + c * (grid.slot_width + grid.gap_x),
                    "y": float(zone.y) + grid.margin + 14 + r * (grid.slot_height + grid.gap_y),
                    "width": grid.slot_width,
                    "height": grid.slot_height,
                    "notes": None,
                }
            )
            number += 1
    return rows


async def _generate_layout(session: AsyncSession, plant: Plant, t: LayoutTemplate) -> None:
    """Geometria inicial: zonas em faixa, docas embaixo, guaritas à esquerda, balança à direita.

    Não tenta ser bonito — tenta ser um ponto de partida legível que o editor ajusta.
    """
    prefix = plant.code
    cols = min(6, max(1, t.slots_per_zone))
    slot_rows = max(1, -(-t.slots_per_zone // cols)) if t.slots_per_zone else 1
    zone_w = max(160.0, 16 * 2 + cols * 45)
    zone_h = max(120.0, 16 * 2 + 14 + slot_rows * 33)
    zone_gap = 20.0

    zones = []
    for i in range(t.zones):
        cold = t.cold_chain_zone and i == t.zones - 1
        zones.append(
            Zone(
                id=uuid4(),
                plant_id=plant.id,
                code=f"{prefix}-Z{chr(65 + i)}",
                kind="cold_chain" if cold else ("staging" if i == 1 else "parking"),
                x=i * (zone_w + zone_gap),
                y=0,
                width=zone_w,
                height=zone_h,
                color_token=f"--color-zone-{'abcdef'[i % 6]}",
            )
        )
    session.add_all(zones)
    await session.flush()

    for zone in zones:
        if t.slots_per_zone:
            grid = SlotGridIn(
                prefix=f"{zone.code}", rows=slot_rows, cols=cols, start_number=1, kind=None
            )
            rows = _grid_rows(zone, grid)[: t.slots_per_zone]
            await session.execute(insert(Slot), rows)

    total_w = t.zones * zone_w + (t.zones - 1) * zone_gap
    dock_w, dock_h, dock_gap = 66.0, 34.0, 8.0
    per_row = max(1, int((total_w + dock_gap) // (dock_w + dock_gap)))
    for i in range(t.docks):
        row, col = divmod(i, per_row)
        session.add(
            Dock(
                id=uuid4(),
                plant_id=plant.id,
                zone_id=None,
                code=f"{prefix}-D{i + 1:02d}",
                direction="inbound" if i < (t.docks + 1) // 2 else "outbound",
                status="available",
                x=col * (dock_w + dock_gap),
                y=zone_h + 60 + row * (dock_h + 8),
                width=dock_w,
                height=dock_h,
            )
        )
    for i in range(t.gates):
        session.add(
            Gate(
                id=uuid4(),
                plant_id=plant.id,
                code=f"{prefix}-G{i + 1:02d}",
                direction="in" if i == 0 else ("out" if i == 1 else "both"),
                x=-55,
                y=30 + i * 70,
                active=True,
            )
        )
    for i in range(t.scales):
        session.add(
            Scale(
                id=uuid4(),
                plant_id=plant.id,
                code=f"{prefix}-S{i + 1:02d}",
                capacity_kg=80000,
                x=total_w + 40,
                y=40 + i * 90,
                active=True,
            )
        )
    await session.flush()
