"""O interlock que define o produto: IA propõe, humano decide, só então o físico acontece."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import (
    ERR_YARD_AI_PROPOSAL_EXPIRED,
    ERR_YARD_AI_PROPOSAL_NOT_APPROVED,
    ERR_YARD_COMMAND_AI_NOT_APPROVED,
    Conflict,
)
from app.modules.gate import service as gate_service
from app.modules.gate.models import AccessCommand, Device
from app.modules.gate.schemas import CommandIn
from app.modules.tower import service
from app.modules.tower.models import AiProposal, BottleneckSignal, HumanDecision
from app.modules.tower.schemas import ApproveIn, RejectIn
from app.modules.visits import service as visit_service
from app.modules.visits.schemas import GateInIn, SlotAssignIn


async def _proposal(session, kind="dwell_alert", payload=None):
    return await service.propose(
        session,
        kind,
        rationale="Veículo parado além da meta.",
        impact={"visits_affected": 1, "minutes_over_target": 45},
        payload=payload or {},
        confidence=0.88,
    )


async def _device(session, fixture_yard, code="BAR-T1"):
    device_id = uuid.uuid4()
    gate_id = (
        await session.execute(text("SELECT id FROM gate WHERE code = 'GATE-T1'"))
    ).scalar_one()
    await session.execute(
        insert(Device),
        [
            {
                "id": device_id,
                "plant_id": fixture_yard["plant"],
                "code": code,
                "kind": "barrier",
                "gate_id": gate_id,
                "protocol": "simulator",
                "status": "online",
            }
        ],
    )
    await session.commit()
    return device_id


async def test_proposta_nasce_proposta(session, fixture_yard):
    proposal = await _proposal(session)
    assert proposal.state == "proposed"
    assert proposal.approved_by is None
    assert proposal.impact_json  # sem impacto calculado não vai para a tela


async def test_execucao_sem_aprovacao_e_recusada(session, fixture_yard):
    proposal = await _proposal(session)
    with pytest.raises(Conflict) as exc:
        await service.execute(session, proposal.id, actor="torre.01")
    assert exc.value.code == ERR_YARD_AI_PROPOSAL_NOT_APPROVED


async def test_aprovacao_registra_quem_decidiu(session, fixture_yard):
    proposal = await _proposal(session)
    proposal_id = proposal.id
    await service.approve(
        session, proposal_id, ApproveIn(approved_by="supervisor.turno", note="ok")
    )
    session.expire_all()
    stored = (
        await session.execute(select(AiProposal).where(AiProposal.id == proposal_id))
    ).scalar_one()
    assert stored.state == "approved" and stored.approved_by == "supervisor.turno"

    decisions = (
        await session.execute(
            select(HumanDecision).where(HumanDecision.proposal_id == proposal_id)
        )
    ).scalars().all()
    assert len(decisions) == 1 and decisions[0].decision == "approved"


async def test_decisao_humana_e_append_only(session, fixture_yard):
    proposal = await _proposal(session)
    proposal_id = proposal.id
    await service.approve(session, proposal_id, ApproveIn(approved_by="supervisor.turno"))
    decision_id = (
        await session.execute(
            select(HumanDecision.id).where(HumanDecision.proposal_id == proposal_id)
        )
    ).scalar_one()

    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            text("UPDATE human_decision SET decided_by = 'outro' WHERE id = :id"),
            {"id": decision_id},
        )
        await session.commit()
    await session.rollback()


async def test_proposta_expirada_nao_executa(session, fixture_yard):
    proposal = await _proposal(session)
    proposal_id = proposal.id
    await service.approve(session, proposal_id, ApproveIn(approved_by="supervisor.turno"))
    await session.execute(
        text("UPDATE ai_proposal SET expires_at = now() - interval '1 minute' WHERE id = :id"),
        {"id": proposal_id},
    )
    await session.commit()
    session.expire_all()

    with pytest.raises(Conflict) as exc:
        await service.execute(session, proposal_id, actor="torre.01")
    assert exc.value.code == ERR_YARD_AI_PROPOSAL_EXPIRED


async def test_comando_fisico_de_proposta_nao_aprovada_e_barrado_pelo_banco(
    session, fixture_yard
):
    """Mesmo forçando por SQL: o trigger recusa comando ligado a proposta não aprovada."""
    device_id = await _device(session, fixture_yard)
    proposal = await _proposal(session, kind="gate_command")
    proposal_id = proposal.id

    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            insert(AccessCommand),
            [
                {
                    "id": uuid.uuid4(),
                    "requested_at": service.now(),
                    "device_id": device_id,
                    "action": "open_barrier",
                    "state": "requested",
                    "origin": "ai",
                    "ai_proposal_id": proposal_id,
                    "approved_by": "alguem",
                    "approved_at": service.now(),
                }
            ],
        )
        await session.commit()
    await session.rollback()


async def test_comando_de_ia_aprovado_passa_pelo_trigger(session, fixture_yard):
    await _device(session, fixture_yard, code="BAR-T9")
    proposal = await _proposal(session, kind="gate_command")
    proposal_id = proposal.id
    await service.approve(session, proposal_id, ApproveIn(approved_by="supervisor.turno"))

    for _ in range(12):  # o permissivo simulado nega de vez em quando
        try:
            command = await gate_service.command(
                session,
                CommandIn(
                    device_code="BAR-T9",
                    action="open_barrier",
                    origin="ai",
                    authorized_by="torre.01",
                    approved_by="supervisor.turno",
                    ai_proposal_id=proposal_id,
                ),
            )
            break
        except Conflict as exc:
            assert exc.code != ERR_YARD_COMMAND_AI_NOT_APPROVED
    else:  # pragma: no cover
        raise AssertionError("permissivo negou doze vezes seguidas")

    assert command.state == "acknowledged"
    assert command.ai_proposal_id == proposal_id


async def test_rejeicao_guarda_motivo(session, fixture_yard):
    proposal = await _proposal(session)
    proposal_id = proposal.id
    await service.reject(
        session,
        proposal_id,
        RejectIn(rejected_by="torre.01", reason_code="OPERATOR_KNOWS_BETTER"),
    )
    session.expire_all()
    stored = (
        await session.execute(select(AiProposal).where(AiProposal.id == proposal_id))
    ).scalar_one()
    assert stored.state == "rejected"
    assert stored.rejected_reason_code == "OPERATOR_KNOWS_BETTER"


async def test_execucao_de_remanejo_gera_tarefa_de_manobra(session, fixture_yard):
    """Proposta aprovada de remanejo vira tarefa na fila — com rastro de quem aprovou."""
    visit = await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A01",
            driver_document="10000000001",
            operation_type_code="RECEBIMENTO_GRANEL",
        ),
    )
    visit_id = visit.id
    await visit_service.assign_slot(session, visit_id, SlotAssignIn(slot_code="T-01"))

    proposal = await service.propose(
        session,
        "slot_reassign",
        rationale="Vaga T-02 fica mais perto da doca atribuída.",
        impact={"distance_saved_m": 120},
        payload={"visit_id": str(visit_id), "to_slot_code": "T-02"},
        confidence=0.8,
    )
    proposal_id = proposal.id
    await service.approve(session, proposal_id, ApproveIn(approved_by="supervisor.turno"))
    executed = await service.execute(session, proposal_id, actor="torre.01")
    assert executed.state == "executed"

    tasks = (
        await session.execute(text("SELECT count(*) FROM move_task WHERE state = 'queued'"))
    ).scalar_one()
    assert tasks == 1


async def test_gargalo_vira_alarme_reconhecivel(session, fixture_yard):
    """Alarme ISA-18.2: nasce aberto, alguém reconhece, e o reconhecimento tem dono."""
    signal = BottleneckSignal(
        detected_at=service.now(),
        scope="gate",
        severity="high",
        metric="gate_queue",
        value=12,
        threshold=8,
        state="open",
    )
    session.add(signal)
    await session.commit()
    signal_id = signal.id

    acknowledged = await service.acknowledge_bottleneck(session, signal_id, "torre.01")
    assert acknowledged.state == "acknowledged"
    assert acknowledged.acknowledged_by == "torre.01"
    assert acknowledged.acknowledged_at is not None


async def test_previsao_de_liberacao_usa_historico(session, fixture_yard):
    visit = await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A01",
            driver_document="10000000001",
            operation_type_code="RECEBIMENTO_GRANEL",
        ),
    )
    forecast = await service.forecast_release(session, visit.id)
    assert forecast.predicted_release_at > service.now()
    assert forecast.model_version == service.MODEL_VERSION


async def test_propostas_vencidas_saem_da_tela(session, fixture_yard):
    proposal = await _proposal(session)
    await session.execute(
        text("UPDATE ai_proposal SET expires_at = now() - interval '5 minutes' WHERE id = :id"),
        {"id": proposal.id},
    )
    await session.commit()
    expired = await service.expire_stale(session)
    assert expired == 1
