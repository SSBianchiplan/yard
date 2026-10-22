"""Movimentação e doca: custo de movimento, confirmação por leitura e bloqueio de saída."""

import uuid

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import (
    ERR_YARD_DISCREPANCY_NEEDS_EVIDENCE,
    ERR_YARD_DOCK_STAGE_INVALID,
    ERR_YARD_EXIT_BLOCKED_BY_PENDENCY,
    ERR_YARD_HOLD_SEGREGATION,
    ERR_YARD_MOVE_ALREADY_ACTIVE,
    ERR_YARD_MOVE_CONFIRMATION_REQUIRED,
    ERR_YARD_MOVE_WRONG_SLOT,
    Conflict,
)
from app.modules.moves import service
from app.modules.moves.models import DockVisit, MoveDeviation, MoveTask, Spotter, VisitHold
from app.modules.moves.schemas import (
    ConfirmMoveIn,
    CreateMoveIn,
    DiscrepancyIn,
    DockStageIn,
    HoldIn,
    HoldReleaseIn,
)
from app.modules.visits import service as visit_service
from app.modules.visits.schemas import GateInIn, GateOutIn, SlotAssignIn


async def _spotter(session, fixture_yard, code="MAN-01"):
    spotter_id = uuid.uuid4()
    await session.execute(
        insert(Spotter),
        [
            {
                "id": spotter_id,
                "plant_id": fixture_yard["plant"],
                "code": code,
                "full_name": "Manobrista Teste",
                "active": True,
            }
        ],
    )
    await session.commit()
    return spotter_id


async def _visit_in_yard(
    session, plate="TST1A01", document="10000000001", slot_code="T-01"
):
    visit = await visit_service.gate_in(
        session,
        GateInIn(plate=plate, driver_document=document, operation_type_code="RECEBIMENTO_GRANEL"),
    )
    visit_id = visit.id
    reference = visit.reference
    await visit_service.assign_slot(session, visit_id, SlotAssignIn(slot_code=slot_code))
    return visit_id, reference


async def test_fila_ordena_por_custo_nao_por_chegada(session, fixture_yard):
    """Tarefa mais barata vai antes — em pátio grande, distância é dinheiro."""
    await _spotter(session, fixture_yard)
    visit_a, ref_a = await _visit_in_yard(session)
    visit_b, ref_b = await _visit_in_yard(session, plate="TST1A02", slot_code="T-02")

    # A primeira criada tem prazo folgado; a segunda está com SLA apertado.
    await service.create_task(
        session, CreateMoveIn(visit_reference=ref_a, to_slot_code="T-02", sla_minutes=600)
    )
    urgent = await service.create_task(
        session, CreateMoveIn(visit_reference=ref_b, to_slot_code="T-01", sla_minutes=5)
    )
    queue = await service.queue(session)
    assert queue[0].reference == urgent.reference


async def test_uma_tarefa_ativa_por_veiculo(session, fixture_yard):
    _, reference = await _visit_in_yard(session)
    await service.create_task(session, CreateMoveIn(visit_reference=reference, to_slot_code="T-02"))
    with pytest.raises(Conflict) as exc:
        await service.create_task(
            session, CreateMoveIn(visit_reference=reference, to_slot_code="T-02")
        )
    assert exc.value.code == ERR_YARD_MOVE_ALREADY_ACTIVE


async def test_evento_offline_reenviado_nao_duplica_tarefa(session, fixture_yard):
    """PWA sem rede reenvia o lote; idempotência é índice único, não boa vontade."""
    _, reference = await _visit_in_yard(session)
    first = await service.create_task(
        session,
        CreateMoveIn(visit_reference=reference, to_slot_code="T-02", client_event_id="evt-001"),
    )
    again = await service.create_task(
        session,
        CreateMoveIn(visit_reference=reference, to_slot_code="T-02", client_event_id="evt-001"),
    )
    assert first.id == again.id
    total = (await session.execute(select(MoveTask))).scalars().all()
    assert len(total) == 1


async def test_confirmacao_por_qr_move_o_veiculo(session, fixture_yard):
    await _spotter(session, fixture_yard)
    visit_id, reference = await _visit_in_yard(session)
    task = await service.create_task(
        session, CreateMoveIn(visit_reference=reference, to_slot_code="T-02")
    )
    task_id = task.id
    await service.accept(session, task_id, "MAN-01")
    await service.start(session, task_id)
    await service.confirm(session, task_id, ConfirmMoveIn(kind="qr", value="T-02"))

    slot_code = (
        await session.execute(
            text(
                "SELECT s.code FROM visit v JOIN slot s ON s.id = v.current_slot_id"
                " WHERE v.id = :id"
            ),
            {"id": visit_id},
        )
    ).scalar_one()
    assert slot_code == "T-02"

    # A ocupação antiga foi encerrada: o veículo não fica em duas vagas.
    open_occupancies = (
        await session.execute(
            text("SELECT count(*) FROM slot_occupancy WHERE visit_id = :v AND ended_at IS NULL"),
            {"v": visit_id},
        )
    ).scalar_one()
    assert open_occupancies == 1


async def test_qr_de_vaga_errada_vira_desvio(session, fixture_yard):
    """Ativo parado em vaga diferente da atribuída gera desvio, não um 'ok'."""
    await _spotter(session, fixture_yard)
    _, reference = await _visit_in_yard(session)
    task = await service.create_task(
        session, CreateMoveIn(visit_reference=reference, to_slot_code="T-02")
    )
    task_id = task.id
    await service.accept(session, task_id, "MAN-01")
    await service.start(session, task_id)

    with pytest.raises(Conflict) as exc:
        await service.confirm(session, task_id, ConfirmMoveIn(kind="qr", value="T-99"))
    assert exc.value.code == ERR_YARD_MOVE_WRONG_SLOT

    deviations = (await session.execute(select(MoveDeviation))).scalars().all()
    assert len(deviations) == 1 and deviations[0].state == "open"


async def test_confirmacao_manual_exige_motivo(session, fixture_yard):
    await _spotter(session, fixture_yard)
    _, reference = await _visit_in_yard(session)
    task = await service.create_task(
        session, CreateMoveIn(visit_reference=reference, to_slot_code="T-02")
    )
    task_id = task.id
    await service.accept(session, task_id, "MAN-01")
    await service.start(session, task_id)

    with pytest.raises(Conflict) as exc:
        await service.confirm(session, task_id, ConfirmMoveIn(kind="manual"))
    assert exc.value.code == ERR_YARD_MOVE_CONFIRMATION_REQUIRED

    await service.confirm(
        session, task_id, ConfirmMoveIn(kind="manual", reason_code="QR_DAMAGED")
    )
    session.expire_all()
    stored = (await session.execute(select(MoveTask).where(MoveTask.id == task_id))).scalar_one()
    assert stored.state == "confirmed" and stored.reason_code == "QR_DAMAGED"


async def test_confirmacao_sem_evidencia_nao_passa_nem_por_sql(session, fixture_yard):
    _, reference = await _visit_in_yard(session)
    task = await service.create_task(
        session, CreateMoveIn(visit_reference=reference, to_slot_code="T-02")
    )
    task_id = task.id
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            text(
                "UPDATE move_task SET state = 'confirmed', confirmation_kind = NULL"
                " WHERE id = :id"
            ),
            {"id": task_id},
        )
        await session.commit()
    await session.rollback()


async def test_cronometria_de_doca_respeita_a_ordem(session, fixture_yard):
    visit_id, _ = await _visit_in_yard(session)
    await service.dock_stage(session, visit_id, DockStageIn(stage="arrived", dock_code="DOCK-T1"))

    # Não se começa a operação sem encostar.
    with pytest.raises(Conflict) as exc:
        await service.dock_stage(session, visit_id, DockStageIn(stage="started"))
    assert exc.value.code == ERR_YARD_DOCK_STAGE_INVALID

    await service.dock_stage(session, visit_id, DockStageIn(stage="docked"))
    await service.dock_stage(session, visit_id, DockStageIn(stage="started"))

    # Pausa sem motivo não existe: é daí que sai a análise de gargalo.
    with pytest.raises(Conflict):
        await service.dock_stage(session, visit_id, DockStageIn(stage="pause"))
    await service.dock_stage(
        session, visit_id, DockStageIn(stage="pause", reason_code="NO_FORKLIFT")
    )
    await service.dock_stage(session, visit_id, DockStageIn(stage="resume"))
    await service.dock_stage(session, visit_id, DockStageIn(stage="finished"))
    await service.dock_stage(session, visit_id, DockStageIn(stage="released"))

    dock_visit = (
        await session.execute(select(DockVisit).where(DockVisit.visit_id == visit_id))
    ).scalar_one()
    assert dock_visit.state == "released"
    assert dock_visit.docked_at and dock_visit.started_at and dock_visit.finished_at


async def test_divergencia_exige_foto_e_abre_pendencia(session, fixture_yard):
    visit_id, _ = await _visit_in_yard(session)
    await service.dock_stage(session, visit_id, DockStageIn(stage="arrived", dock_code="DOCK-T1"))
    dock_visit = (
        await session.execute(select(DockVisit).where(DockVisit.visit_id == visit_id))
    ).scalar_one()
    dock_visit_id = dock_visit.id

    with pytest.raises(Conflict) as exc:
        await service.report_discrepancy(
            session,
            dock_visit_id,
            DiscrepancyIn(kind="damage", evidence_ref="", reported_by="conferente.01"),
        )
    assert exc.value.code == ERR_YARD_DISCREPANCY_NEEDS_EVIDENCE

    await service.report_discrepancy(
        session,
        dock_visit_id,
        DiscrepancyIn(
            kind="damage", evidence_ref="s3://yard/avaria.jpg", reported_by="conferente.01"
        ),
    )
    blocked = (
        await session.execute(
            text("SELECT blocked_reason_code FROM visit WHERE id = :id"), {"id": visit_id}
        )
    ).scalar_one()
    assert blocked == "DISCREPANCY_DAMAGE"

    session.expire_all()
    with pytest.raises(Conflict) as exc:
        await visit_service.gate_out(session, visit_id, GateOutIn())
    assert exc.value.code == ERR_YARD_EXIT_BLOCKED_BY_PENDENCY


async def test_quem_abre_pendencia_nao_libera(session, fixture_yard):
    """Segregação de função: o mesmo usuário não abre e fecha a própria pendência."""
    visit_id, _ = await _visit_in_yard(session)
    hold = await service.open_hold(
        session,
        visit_id,
        HoldIn(kind="fiscal", reason_code="MISSING_NFE", opened_by="fiscal.01"),
    )
    hold_id = hold.id

    with pytest.raises(Conflict) as exc:
        await service.release_hold(session, hold_id, HoldReleaseIn(released_by="fiscal.01"))
    assert exc.value.code == ERR_YARD_HOLD_SEGREGATION

    await service.release_hold(session, hold_id, HoldReleaseIn(released_by="supervisor.01"))
    session.expire_all()
    stored = (
        await session.execute(select(VisitHold).where(VisitHold.id == hold_id))
    ).scalar_one()
    assert stored.released_by == "supervisor.01"

    # Última pendência liberada: o veículo volta a poder sair.
    blocked = (
        await session.execute(
            text("SELECT blocked_reason_code FROM visit WHERE id = :id"), {"id": visit_id}
        )
    ).scalar_one()
    assert blocked is None


async def test_doca_nao_recebe_dois_veiculos_ao_mesmo_tempo(session, fixture_yard):
    visit_a, _ = await _visit_in_yard(session)
    visit_b, _ = await _visit_in_yard(session, plate="TST1A02", slot_code="T-02")
    await service.dock_stage(session, visit_a, DockStageIn(stage="arrived", dock_code="DOCK-T1"))
    with pytest.raises((IntegrityError, DBAPIError, Conflict)):
        await service.dock_stage(
            session, visit_b, DockStageIn(stage="arrived", dock_code="DOCK-T1")
        )
    await session.rollback()


async def test_saida_do_patio_libera_a_doca_para_o_proximo(session, fixture_yard):
    """Sair do pátio fecha a ocupação da doca — senão a doca fica presa para sempre.

    A ocupação vive em `dock_visit` com EXCLUDE de período: enquanto `released_at` é nulo,
    o intervalo é aberto e nenhum outro veículo encosta. O gate-out limpava o vínculo na
    visita mas deixava a ocupação aberta, e a doca sumia da operação sem nada na tela.
    """
    visit_a, _ = await _visit_in_yard(session, plate="TST1B01", document="10000000001")
    await service.dock_stage(session, visit_a, DockStageIn(stage="arrived", dock_code="DOCK-T1"))
    await visit_service.gate_out(session, visit_a, GateOutIn())

    open_after_exit = (
        await session.execute(
            select(DockVisit.id).where(
                DockVisit.visit_id == visit_a, DockVisit.released_at.is_(None)
            )
        )
    ).scalars().all()
    assert open_after_exit == []

    # E a prova que importa: a doca aceita o próximo veículo.
    visit_b, _ = await _visit_in_yard(
        session, plate="TST1B02", document="10000000001", slot_code="T-02"
    )
    await service.dock_stage(session, visit_b, DockStageIn(stage="arrived", dock_code="DOCK-T1"))
