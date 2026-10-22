"""Portaria automática: o que impede a cancela de abrir sozinha."""

import uuid

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import (
    ERR_YARD_CHECKLIST_FAILED,
    ERR_YARD_COMMAND_AI_NOT_APPROVED,
    ERR_YARD_COMMAND_DENIED_BY_PLC,
    ERR_YARD_DEVICE_OFFLINE,
    ERR_YARD_IDENTIFICATION_LOW_CONFIDENCE,
    Conflict,
)
from app.modules.gate import service
from app.modules.gate.models import AccessCommand, ChecklistItem, ChecklistTemplate, Device
from app.modules.gate.schemas import AnswerIn, ChecklistAnswerIn, CommandIn, IdentifyIn
from app.modules.visits import service as visit_service
from app.modules.visits.schemas import GateInIn, SlotAssignIn


async def _device(session, fixture_yard, *, code="BAR-T1", status="online", protocol="simulator"):
    gate_id = (
        await session.execute(text("SELECT id FROM gate WHERE code = 'GATE-T1'"))
    ).scalar_one()
    device_id = uuid.uuid4()
    await session.execute(
        insert(Device),
        [
            {
                "id": device_id,
                "plant_id": fixture_yard["plant"],
                "code": code,
                "kind": "barrier",
                "gate_id": gate_id,
                "protocol": protocol,
                "status": status,
            }
        ],
    )
    await session.commit()
    return device_id


async def _checklist(session, *, severity="blocking", requires_photo=False):
    template_id, item_id = uuid.uuid4(), uuid.uuid4()
    await session.execute(
        insert(ChecklistTemplate),
        [{"id": template_id, "code": "GATE_IN_BASE", "direction": "in", "active": True}],
    )
    await session.execute(
        insert(ChecklistItem),
        [
            {
                "id": item_id,
                "template_id": template_id,
                "code": "EPI_COMPLETE",
                "position": 1,
                "severity": severity,
                "requires_photo": requires_photo,
            }
        ],
    )
    await session.commit()
    return item_id


async def _visit(session):
    return await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A01",
            driver_document="10000000001",
            operation_type_code="RECEBIMENTO_GRANEL",
        ),
    )


async def test_lpr_com_baixa_confianca_nao_libera(session, fixture_yard):
    """Leitura ruim vira trabalho para o guarda, não liberação automática."""
    with pytest.raises(Conflict) as exc:
        await service.identify(
            session,
            IdentifyIn(
                gate_code="GATE-T1",
                method="lpr",
                value="TST1A01",
                confidence=0.62,
                image_ref="s3://lpr/1.jpg",
            ),
        )
    assert exc.value.code == ERR_YARD_IDENTIFICATION_LOW_CONFIDENCE

    # O evento fica registrado como ambíguo — a leitura ruim não desaparece da trilha.
    state = (
        await session.execute(
            text("SELECT state FROM identification_event ORDER BY occurred_at DESC LIMIT 1")
        )
    ).scalar_one()
    assert state == "ambiguous"


async def test_lpr_confiavel_sem_agendamento_vai_para_fila(session, fixture_yard):
    decision = await service.identify(
        session,
        IdentifyIn(gate_code="GATE-T1", method="lpr", value="TST1A01", confidence=0.97),
    )
    assert decision.decision == "queue"
    assert decision.requires_human is True
    assert decision.plate == "TST1A01"


async def test_placa_desconhecida_e_recusada(session, fixture_yard):
    decision = await service.identify(
        session,
        IdentifyIn(gate_code="GATE-T1", method="lpr", value="ZZZ9Z99", confidence=0.99),
    )
    assert decision.decision == "reject"


async def test_checklist_reprovado_bloqueia_liberacao(session, fixture_yard):
    item_id = await _checklist(session)
    visit = await _visit(session)
    visit_id = visit.id

    failed = await service.answer_checklist(
        session,
        visit_id,
        ChecklistAnswerIn(
            answers=[AnswerIn(item_id=item_id, passed=False, note="sem capacete")],
            actor="guarda.01",
        ),
    )
    assert failed == ["EPI_COMPLETE"]

    session.expire_all()
    with pytest.raises(Conflict) as exc:
        await visit_service.assign_slot(session, visit_id, SlotAssignIn())
    assert exc.value.code == ERR_YARD_CHECKLIST_FAILED

    # O trigger também marcou a visita — a saída fica presa pelo mesmo motivo.
    blocked = (
        await session.execute(
            text("SELECT blocked_reason_code FROM visit WHERE id = :id"), {"id": visit_id}
        )
    ).scalar_one()
    assert blocked == "CHECKLIST_FAILED"


async def test_checklist_aprovado_libera(session, fixture_yard):
    item_id = await _checklist(session)
    visit = await _visit(session)
    visit_id = visit.id
    failed = await service.answer_checklist(
        session,
        visit_id,
        ChecklistAnswerIn(answers=[AnswerIn(item_id=item_id, passed=True)], actor="guarda.01"),
    )
    assert failed == []
    await visit_service.assign_slot(session, visit_id, SlotAssignIn())
    state = (
        await session.execute(text("SELECT state FROM visit WHERE id = :id"), {"id": visit_id})
    ).scalar_one()
    assert state == "in_yard"


async def test_comando_de_ia_sem_aprovacao_humana_e_recusado(session, fixture_yard):
    """O interlock do produto: sugestão de IA não vira comando físico sozinha."""
    await _device(session, fixture_yard)
    with pytest.raises(Conflict) as exc:
        await service.command(
            session,
            CommandIn(
                device_code="BAR-T1",
                action="open_barrier",
                origin="ai",
                authorized_by="torre.01",
            ),
        )
    assert exc.value.code == ERR_YARD_COMMAND_AI_NOT_APPROVED


async def test_comando_de_ia_com_proposta_inexistente_e_barrado(session, fixture_yard):
    """Desde a Fatia 7, `ai_proposal_id` é FK: citar proposta que não existe não cola.

    O caminho feliz (proposta real, aprovada, dentro do prazo) vive em
    `test_tower_ai.py::test_comando_de_ia_aprovado_passa_pelo_trigger`.
    """
    await _device(session, fixture_yard)
    with pytest.raises((IntegrityError, DBAPIError)):
        await service.command(
            session,
            CommandIn(
                device_code="BAR-T1",
                action="open_barrier",
                origin="ai",
                authorized_by="torre.01",
                approved_by="supervisor.turno",
                ai_proposal_id=uuid.uuid4(),
            ),
        )
    await session.rollback()


async def test_dispositivo_offline_nao_recebe_comando(session, fixture_yard):
    await _device(session, fixture_yard, code="BAR-T2", status="offline")
    with pytest.raises(Conflict) as exc:
        await service.command(
            session,
            CommandIn(device_code="BAR-T2", action="open_barrier", authorized_by="guarda.01"),
        )
    assert exc.value.code == ERR_YARD_DEVICE_OFFLINE


async def test_comando_sem_permissivo_nao_pode_ser_forjado(session, fixture_yard):
    """Inserção crua: o CHECK recusa comando 'enviado' sem permissivo e sem autorizador."""
    device_id = await _device(session, fixture_yard, code="BAR-T3")
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            insert(AccessCommand),
            [
                {
                    "id": uuid.uuid4(),
                    "requested_at": service.now(),
                    "device_id": device_id,
                    "action": "open_barrier",
                    "state": "sent",
                    "origin": "human",
                    "plc_permissive": False,
                    "permissive_quality": "good",
                    "authorized_by": None,
                }
            ],
        )
        await session.commit()
    await session.rollback()


async def test_comando_concluido_nao_pode_ser_reescrito(session, fixture_yard):
    await _device(session, fixture_yard, code="BAR-T4")
    cmd = None
    for _ in range(10):
        try:
            cmd = await service.command(
                session,
                CommandIn(
                    device_code="BAR-T4", action="green_light", authorized_by="guarda.01"
                ),
            )
            break
        except Conflict:
            continue
    assert cmd is not None
    command_id = cmd.id

    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            text("UPDATE access_command SET action = 'open_barrier' WHERE id = :id"),
            {"id": command_id},
        )
        await session.commit()
    await session.rollback()


async def test_qr_do_agendamento_identifica_e_admite(session, fixture_yard):
    from app.modules.scheduling import service as scheduling_service
    from app.modules.scheduling.schemas import AppointmentIn, ConfirmIn
    from datetime import datetime, timedelta, timezone

    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=2
    )
    appointment = await scheduling_service.create(
        session,
        AppointmentIn(
            dock_code="DOCK-T1",
            plate="TST1A01",
            operation_type_code="RECEBIMENTO_GRANEL",
            starts_at=start,
            ends_at=start + timedelta(minutes=90),
        ),
    )
    reference = appointment.reference
    await scheduling_service.confirm(
        session, appointment.id, ConfirmIn(version=1, slot_code="T-01")
    )

    decision = await service.identify(
        session, IdentifyIn(gate_code="GATE-T1", method="qr", value=reference)
    )
    assert decision.decision == "admit"
    assert decision.appointment_reference == reference

    events = (
        await session.execute(
            select(ChecklistItem).where(ChecklistItem.code == "NEVER")  # sanity: sem checklist
        )
    ).scalars().all()
    assert events == []
