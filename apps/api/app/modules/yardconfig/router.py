from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires
from app.modules.yard.models import Dock, Gate, Scale, Slot, Zone
from app.modules.yardconfig import schemas as s
from app.modules.yardconfig import service

router = APIRouter(
    prefix="/yard-config",
    tags=["yard-config"],
    dependencies=[Depends(requires(Role.ADMIN))],
)

# Leitura da lista de pátios serve à troca de pátio no cabeçalho — qualquer operador.
plants_read_router = APIRouter(prefix="/yard-config", tags=["yard-config"])


@plants_read_router.get(
    "/plants",
    response_model=list[s.PlantOut],
    dependencies=[
        Depends(requires(Role.GATE, Role.CONTROLLER, Role.SPOTTER, Role.SCHEDULER, Role.SCALE))
    ],
)
async def list_plants(session: AsyncSession = Depends(get_session)):
    return await service.plant_summaries(session)


@router.post("/plants", response_model=s.PlantOut, status_code=201)
async def create_plant(payload: s.PlantCreateIn, session: AsyncSession = Depends(get_session)):
    data = payload.model_dump(exclude={"template"})
    plant = await service.create_plant(session, data, payload.template)
    return (await service.plant_summaries(session, plant.id))[0]


@router.patch("/plants/{plant_id}", response_model=s.PlantOut)
async def update_plant(
    plant_id: UUID, payload: s.PlantPatch, session: AsyncSession = Depends(get_session)
):
    await service.update_plant(session, plant_id, payload.model_dump(exclude_unset=True))
    return (await service.plant_summaries(session, plant_id))[0]


@router.get("/plants/{plant_id}/layout", response_model=s.LayoutOut)
async def layout(plant_id: UUID, session: AsyncSession = Depends(get_session)):
    await service.get_plant(session, plant_id)

    async def rows(model):
        return (
            (
                await session.execute(
                    select(model).where(model.plant_id == plant_id).order_by(model.code)
                )
            )
            .scalars()
            .all()
        )

    return s.LayoutOut(
        plant=(await service.plant_summaries(session, plant_id))[0],
        zones=await rows(Zone),
        slots=await rows(Slot),
        docks=await rows(Dock),
        gates=await rows(Gate),
        scales=await rows(Scale),
    )


def _register(entity: str, plural: str, schema_in, schema_patch, schema_out) -> None:
    @router.post(
        f"/plants/{{plant_id}}/{plural}",
        response_model=schema_out,
        status_code=201,
        name=f"create_{entity}",
    )
    async def _create(
        plant_id: UUID,
        payload: schema_in,  # type: ignore[valid-type]
        session: AsyncSession = Depends(get_session),
    ):
        return await service.create_element(session, entity, plant_id, payload.model_dump())

    @router.patch(f"/{plural}/{{element_id}}", response_model=schema_out, name=f"update_{entity}")
    async def _update(
        element_id: UUID,
        payload: schema_patch,  # type: ignore[valid-type]
        session: AsyncSession = Depends(get_session),
    ):
        return await service.update_element(
            session, entity, element_id, payload.model_dump(exclude_unset=True)
        )

    @router.delete(f"/{plural}/{{element_id}}", status_code=204, name=f"delete_{entity}")
    async def _delete(element_id: UUID, session: AsyncSession = Depends(get_session)):
        await service.delete_element(session, entity, element_id)
        return Response(status_code=204)


_register("zone", "zones", s.ZoneIn, s.ZonePatch, s.ZoneOut)
_register("slot", "slots", s.SlotIn, s.SlotPatch, s.SlotOut)
_register("dock", "docks", s.DockIn, s.DockPatch, s.DockOut)
_register("gate", "gates", s.GateIn, s.GatePatch, s.GateOut)
_register("scale", "scales", s.ScaleIn, s.ScalePatch, s.ScaleOut)


@router.post("/zones/{zone_id}/slots/generate", response_model=list[s.SlotOut], status_code=201)
async def generate_slots(
    zone_id: UUID, payload: s.SlotGridIn, session: AsyncSession = Depends(get_session)
):
    return await service.generate_slots(session, zone_id, payload)
