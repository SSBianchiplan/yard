"""Configuração de pátio: assistente, edição, grade de vagas e o que não se apaga."""

import pytest
from sqlalchemy import select

from app.core.errors import AppError, Conflict
from app.modules.catalog.models import Plant
from app.modules.visits import service as visits
from app.modules.visits.schemas import GateInIn, SlotAssignIn
from app.modules.yard.models import Gate, Slot
from app.modules.yardconfig import service
from app.modules.yardconfig.schemas import LayoutTemplate, SlotGridIn


async def _new_yard(session, code="CD-2", **template):
    plant = await service.create_plant(
        session,
        {"code": code, "name": "Centro de Distribuição 2", "timezone": "America/Sao_Paulo",
         "segment": "food", "city": "Jundiaí", "description": None, "active": True},
        LayoutTemplate(**template) if template is not None else None,
    )
    return plant


async def test_assistente_gera_layout_prefixado(session):
    plant = await _new_yard(session, zones=3, slots_per_zone=10, docks=4, gates=2, scales=1,
                            cold_chain_zone=True)
    summary = (await service.plant_summaries(session, plant.id))[0]
    assert (summary.zones, summary.slots, summary.docks, summary.gates, summary.scales) == (
        3, 30, 4, 2, 1)
    codes = (await session.execute(select(Slot.code).where(Slot.plant_id == plant.id))).scalars()
    assert all(code.startswith("CD-2-Z") for code in codes)
    kinds = (await session.execute(select(Slot.kind).where(Slot.plant_id == plant.id))).scalars()
    assert "cold_chain" in set(kinds)


async def test_codigo_duplicado_vira_erro_traduzivel(session):
    await _new_yard(session, zones=1, slots_per_zone=1, docks=0, gates=1, scales=0)
    with pytest.raises(Conflict) as exc:
        await _new_yard(session, zones=1, slots_per_zone=1, docks=0, gates=1, scales=0)
    assert exc.value.code == "ERR_YARD_CODE_TAKEN"


async def test_grade_de_vagas_e_edicao(session):
    plant = await _new_yard(session, zones=1, slots_per_zone=0, docks=0, gates=1, scales=0)
    layout_zone = (
        await session.execute(select(service.Zone).where(service.Zone.plant_id == plant.id))
    ).scalar_one()
    slots = await service.generate_slots(
        session, layout_zone.id, SlotGridIn(prefix="cd2-r", rows=2, cols=3)
    )
    assert [s.code for s in slots][:2] == ["CD2-R-01", "CD2-R-02"] and len(slots) == 6
    edited = await service.update_element(
        session, "slot", slots[0].id, {"status": "maintenance", "x": 5}
    )
    assert edited.status == "maintenance" and float(edited.x) == 5
    await service.delete_element(session, "slot", slots[1].id)
    with pytest.raises(Conflict):
        await service.generate_slots(
            session, layout_zone.id, SlotGridIn(prefix="cd2-r", rows=1, cols=1)
        )


async def test_zona_de_outro_patio_recusada(session):
    a = await _new_yard(session, code="PA", zones=1, slots_per_zone=0, docks=0, gates=1, scales=0)
    b = await _new_yard(session, code="PB", zones=1, slots_per_zone=0, docks=0, gates=1, scales=0)
    zone_b = (
        await session.execute(select(service.Zone).where(service.Zone.plant_id == b.id))
    ).scalar_one()
    with pytest.raises(AppError) as exc:
        await service.create_element(
            session, "slot", a.id,
            {"code": "PA-X", "zone_id": zone_b.id, "kind": "parking", "status": "available",
             "length_m": 18, "x": 0, "y": 0, "width": 10, "height": 10, "notes": None},
        )
    assert exc.value.code == "ERR_YARD_ZONE_OTHER_PLANT"


async def test_vaga_com_historico_nao_se_apaga_e_visita_fica_no_patio_da_guarita(
    session, fixture_yard
):
    plant = await _new_yard(session, code="NV", zones=1, slots_per_zone=2, docks=1, gates=2,
                            scales=0)
    gate = (
        await session.execute(select(Gate).where(Gate.plant_id == plant.id, Gate.direction == "in"))
    ).scalar_one()
    visit = await visits.gate_in(
        session,
        GateInIn(plate=fixture_yard["vehicles"][0]["plate"],
                 driver_document=fixture_yard["drivers"][0]["document"],
                 operation_type_code="RECEBIMENTO_GRANEL", gate_code=gate.code, source="manual"),
    )
    plant_id = plant.id
    assert visit.plant_id == plant_id
    visit = await visits.assign_slot(session, visit.id, SlotAssignIn(source="manual"))
    slot = await session.get(Slot, visit.current_slot_id)
    # alocação automática escolheu vaga DO pátio da guarita, não a primeira do sistema
    assert slot.plant_id == plant_id
    with pytest.raises(Conflict) as exc:
        await service.delete_element(session, "slot", slot.id)
    assert exc.value.code == "ERR_YARD_CONFIG_IN_USE"
    # depois do rollback o objeto expira: relê pelo id guardado
    assert (await session.get(Plant, plant_id)) is not None
