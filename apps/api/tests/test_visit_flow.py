"""Máquina de estados da visita e as regras que barram entrada e saída."""

import pytest
from sqlalchemy import select, text

from app.core.errors import (
    ERR_YARD_DRIVER_LICENSE_EXPIRED,
    ERR_YARD_EXIT_BLOCKED_BY_PENDENCY,
    ERR_YARD_INVALID_TRANSITION,
    ERR_YARD_SLOT_BLOCKED,
    ERR_YARD_VEHICLE_ALREADY_IN_YARD,
    Conflict,
)
from app.domain.enums import VisitState
from app.modules.visits import service
from app.modules.visits.models import Visit, VisitEvent
from app.modules.visits.schemas import DockAssignIn, GateInIn, GateOutIn, SlotAssignIn


def _gate_in(plate="TST1A01", document="10000000001") -> GateInIn:
    return GateInIn(
        plate=plate,
        driver_document=document,
        operation_type_code="RECEBIMENTO_GRANEL",
        gate_code="GATE-T1",
        actor="teste",
    )


async def test_ciclo_completo_gera_trilha(session, fixture_yard):
    visit = await service.gate_in(session, _gate_in())
    assert visit.state == VisitState.AT_GATE_IN

    await service.assign_slot(session, visit.id, SlotAssignIn(actor="teste"))
    await session.refresh(visit)
    assert visit.state == VisitState.IN_YARD
    assert visit.gate_in_at is not None
    assert visit.current_slot_id is not None

    await service.assign_dock(session, visit.id, DockAssignIn(dock_code="DOCK-T1"))
    await session.refresh(visit)
    assert visit.state == VisitState.AT_DOCK

    await service.gate_out(session, visit.id, GateOutIn(gate_code="GATE-T2"))
    await session.refresh(visit)
    assert visit.state == VisitState.DEPARTED
    assert visit.current_slot_id is None and visit.current_dock_id is None
    assert service.dwell_seconds(visit) >= 0

    events = (
        await session.execute(select(VisitEvent).where(VisitEvent.visit_id == visit.id))
    ).scalars().all()
    assert {e.event_type for e in events} == {
        "gate_in",
        "slot_assigned",
        "dock_assigned",
        "gate_out",
    }
    # doca devolvida ao pool
    status = (
        await session.execute(text("SELECT status FROM dock WHERE code = 'DOCK-T1'"))
    ).scalar_one()
    assert status == "available"


async def test_veiculo_nao_entra_duas_vezes(session, fixture_yard):
    """Mesma placa, outro motorista válido: o que barra é a visita aberta."""
    await service.gate_in(session, _gate_in())
    with pytest.raises(Conflict) as exc:
        await service.gate_in(session, _gate_in())
    assert exc.value.code == ERR_YARD_VEHICLE_ALREADY_IN_YARD


async def test_cnh_vencida_barra_gate_in(session, fixture_yard):
    with pytest.raises(Conflict) as exc:
        await service.gate_in(session, _gate_in(plate="TST1A02", document="10000000002"))
    assert exc.value.code == ERR_YARD_DRIVER_LICENSE_EXPIRED
    assert (await session.execute(select(Visit))).scalars().first() is None


async def test_transicao_invalida_e_recusada(session, fixture_yard):
    visit = await service.gate_in(session, _gate_in())
    # da guarita não se vai direto para a doca: precisa passar pelo pátio
    with pytest.raises(Conflict) as exc:
        await service.assign_dock(session, visit.id, DockAssignIn(dock_code="DOCK-T1"))
    assert exc.value.code == ERR_YARD_INVALID_TRANSITION


async def test_vaga_em_manutencao_nao_recebe_veiculo(session, fixture_yard):
    visit = await service.gate_in(session, _gate_in())
    with pytest.raises(Conflict) as exc:
        await service.assign_slot(session, visit.id, SlotAssignIn(slot_code="T-99"))
    assert exc.value.code == ERR_YARD_SLOT_BLOCKED


async def test_pendencia_aberta_bloqueia_saida(session, fixture_yard):
    visit = await service.gate_in(session, _gate_in())
    visit_id = visit.id
    await service.assign_slot(session, visit_id, SlotAssignIn())
    await session.execute(
        text("UPDATE visit SET blocked_reason_code = 'PENDING_FISCAL_DOC' WHERE id = :id"),
        {"id": visit_id},
    )
    await session.commit()
    session.expire_all()  # a pendência entrou por fora; a sessão precisa reler
    with pytest.raises(Conflict) as exc:
        await service.gate_out(session, visit_id, GateOutIn())
    assert exc.value.code == ERR_YARD_EXIT_BLOCKED_BY_PENDENCY
