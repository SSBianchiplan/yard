"""Balança: o líquido não pode mentir, e o ticket fechado não pode mudar."""

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import (
    ERR_YARD_TICKET_IMMUTABLE,
    ERR_YARD_WEIGHT_MANUAL_NEEDS_SECOND_FACTOR,
    ERR_YARD_WEIGHT_REENTRY_SUSPECT,
    ERR_YARD_WEIGHT_UNSTABLE,
    ERR_YARD_WEIGHT_VEHICLE_MISPLACED,
    Conflict,
)
from app.modules.visits import service as visit_service
from app.modules.visits.models import Visit
from app.modules.visits.schemas import GateInIn, GateOutIn
from app.modules.weighing import service
from app.modules.weighing.drivers import SimulatorScaleDriver, driver_for, parse_frame
from app.modules.weighing.models import WeighingTicket
from app.modules.weighing.schemas import CaptureIn, CloseTicketIn, OpenTicketIn, ReprintIn


async def _visit(session) -> Visit:
    return await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A01",
            driver_document="10000000001",
            operation_type_code="RECEBIMENTO_GRANEL",
            document_number="NFE123456",
        ),
    )


def _settle(scale_code: str, target_kg: int) -> SimulatorScaleDriver:
    """Deixa o simulador estabilizado no peso alvo, como caminhão parado na plataforma."""
    driver = driver_for(scale_code, "simulator", None)
    assert isinstance(driver, SimulatorScaleDriver)
    driver.set_target(target_kg)
    return driver


async def _stabilize(driver: SimulatorScaleDriver) -> None:
    for _ in range(14):
        sample = await driver.read()
        if sample.stable:
            return
    raise AssertionError("simulador não estabilizou")


def test_parser_toledo_le_estabilidade():
    estavel = parse_frame("\x02S042180\x03", "serial_toledo")
    instavel = parse_frame("\x02I042180\x03", "serial_toledo")
    ilegivel = parse_frame("ruído", "serial_toledo")
    assert (estavel.weight_kg, estavel.stable) == (42180, True)
    assert instavel.stable is False
    # Quadro ilegível não vira zero: vira qualidade inválida.
    assert ilegivel.quality == "invalid"


async def test_ciclo_bruto_tara_liquido_com_hash(session, fixture_yard):
    visit = await _visit(session)
    ticket = await service.open_ticket(
        session,
        OpenTicketIn(
            visit_reference=visit.reference,
            scale_code="SCALE-T1",
            document_number="NFE123456",
            document_net_kg=30000,
            operator="balanceiro",
        ),
    )
    ticket_id = ticket.id

    driver = _settle("SCALE-T1", 42000)
    await _stabilize(driver)
    await service.capture(
        session, ticket_id, CaptureIn(kind="gross", image_ref="s3://img/gross.jpg")
    )

    driver = _settle("SCALE-T1", 12000)
    await _stabilize(driver)
    await service.capture(session, ticket_id, CaptureIn(kind="tare", image_ref="s3://img/tare.jpg"))

    closed = await service.close_ticket(session, ticket_id, CloseTicketIn())
    assert closed.net_kg == closed.gross_kg - closed.tare_kg
    assert closed.state == "closed"
    assert closed.integrity_hash and len(closed.integrity_hash) == 64
    assert closed.tare_source == "measured"


async def test_peso_instavel_nao_vira_ticket(session, fixture_yard):
    visit = await _visit(session)
    ticket = await service.open_ticket(
        session, OpenTicketIn(visit_reference=visit.reference, scale_code="SCALE-T1")
    )
    _settle("SCALE-T1", 40000)  # recém-zerado: ainda oscilando
    with pytest.raises(Conflict) as exc:
        await service.capture(session, ticket.id, CaptureIn(kind="gross", image_ref="s3://a.jpg"))
    assert exc.value.code == ERR_YARD_WEIGHT_UNSTABLE


async def test_veiculo_mal_posicionado_nao_pesa(session, fixture_yard):
    visit = await _visit(session)
    ticket = await service.open_ticket(
        session, OpenTicketIn(visit_reference=visit.reference, scale_code="SCALE-T1")
    )
    driver = _settle("SCALE-T1", 40000)
    await _stabilize(driver)
    with pytest.raises(Conflict) as exc:
        await service.capture(
            session,
            ticket.id,
            CaptureIn(kind="gross", vehicle_positioned=False, image_ref="s3://a.jpg"),
        )
    assert exc.value.code == ERR_YARD_WEIGHT_VEHICLE_MISPLACED


async def test_peso_manual_exige_segundo_fator(session, fixture_yard):
    visit = await _visit(session)
    ticket = await service.open_ticket(
        session, OpenTicketIn(visit_reference=visit.reference, scale_code="SCALE-T1")
    )
    ticket_id = ticket.id
    with pytest.raises(Conflict) as exc:
        await service.capture(
            session,
            ticket_id,
            CaptureIn(kind="gross", manual_weight_kg=41000, reason_code="INDICATOR_DOWN"),
        )
    assert exc.value.code == ERR_YARD_WEIGHT_MANUAL_NEEDS_SECOND_FACTOR

    # Com motivo E segundo humano, passa — e fica marcado como manual para sempre.
    await service.capture(
        session,
        ticket_id,
        CaptureIn(
            kind="gross",
            manual_weight_kg=41000,
            reason_code="INDICATOR_DOWN",
            second_factor_user="supervisor.turno",
            image_ref="s3://manual.jpg",
        ),
    )
    session.expire_all()
    stored = (
        await session.execute(select(WeighingTicket).where(WeighingTicket.id == ticket_id))
    ).scalar_one()
    assert stored.source == "manual"
    assert stored.second_factor_user == "supervisor.turno"


async def test_divergencia_acima_da_tolerancia_bloqueia_saida(session, fixture_yard):
    """Peso × NF-e fora da tolerância: o trigger marca a visita e o gate-out para."""
    visit = await _visit(session)
    visit_id = visit.id
    ticket = await service.open_ticket(
        session,
        OpenTicketIn(
            visit_reference=visit.reference,
            scale_code="SCALE-T1",
            document_net_kg=30000,
            tolerance_pct=0.5,
        ),
    )
    ticket_id = ticket.id

    driver = _settle("SCALE-T1", 45000)
    await _stabilize(driver)
    await service.capture(session, ticket_id, CaptureIn(kind="gross", image_ref="s3://g.jpg"))
    driver = _settle("SCALE-T1", 12000)
    await _stabilize(driver)
    await service.capture(session, ticket_id, CaptureIn(kind="tare", image_ref="s3://t.jpg"))
    closed = await service.close_ticket(session, ticket_id, CloseTicketIn())

    assert closed.net_kg is not None and closed.net_kg > 30000
    assert abs(closed.divergence_pct) > Decimal("0.5")

    blocked = (
        await session.execute(
            text("SELECT blocked_reason_code FROM visit WHERE id = :id"), {"id": visit_id}
        )
    ).scalar_one()
    assert blocked == "WEIGHT_DIVERGENCE"

    session.expire_all()
    with pytest.raises(Conflict):
        await visit_service.gate_out(session, visit_id, GateOutIn())


async def test_ticket_fechado_e_imutavel(session, fixture_yard):
    visit = await _visit(session)
    ticket = await service.open_ticket(
        session, OpenTicketIn(visit_reference=visit.reference, scale_code="SCALE-T1")
    )
    ticket_id = ticket.id
    driver = _settle("SCALE-T1", 44000)
    await _stabilize(driver)
    await service.capture(session, ticket_id, CaptureIn(kind="gross", image_ref="s3://g.jpg"))
    driver = _settle("SCALE-T1", 13000)
    await _stabilize(driver)
    await service.capture(session, ticket_id, CaptureIn(kind="tare", image_ref="s3://t.jpg"))
    await service.close_ticket(session, ticket_id, CloseTicketIn())

    # Pela aplicação: recusado com código traduzível.
    with pytest.raises(Conflict) as exc:
        await service.close_ticket(session, ticket_id, CloseTicketIn())
    assert exc.value.code == ERR_YARD_TICKET_IMMUTABLE

    # Por SQL cru: recusado pelo trigger.
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            text("UPDATE weighing_ticket SET net_kg = 1 WHERE id = :id"), {"id": ticket_id}
        )
        await session.commit()
    await session.rollback()

    # Reimpressão é a única mudança permitida — e fica contada.
    reprinted = await service.reprint(
        session, ticket_id, ReprintIn(actor="balanceiro", reason_code="PRINTER_JAM")
    )
    assert reprinted.reprint_count == 1


async def test_reentrada_suspeita_exige_justificativa(session, fixture_yard):
    visit = await _visit(session)
    ticket = await service.open_ticket(
        session, OpenTicketIn(visit_reference=visit.reference, scale_code="SCALE-T1")
    )
    ticket_id = ticket.id
    driver = _settle("SCALE-T1", 44000)
    await _stabilize(driver)
    await service.capture(session, ticket_id, CaptureIn(kind="gross", image_ref="s3://g.jpg"))
    driver = _settle("SCALE-T1", 13000)
    await _stabilize(driver)
    await service.capture(session, ticket_id, CaptureIn(kind="tare", image_ref="s3://t.jpg"))
    await service.close_ticket(session, ticket_id, CloseTicketIn())

    visit_id = visit.id
    session.expire_all()
    visit_reference = (
        await session.execute(select(Visit.reference).where(Visit.id == visit_id))
    ).scalar_one()
    with pytest.raises(Conflict) as exc:
        await service.open_ticket(
            session, OpenTicketIn(visit_reference=visit_reference, scale_code="SCALE-T1")
        )
    assert exc.value.code == ERR_YARD_WEIGHT_REENTRY_SUSPECT

    # Justificada, entra — e o ticket novo nasce limpo.
    again = await service.open_ticket(
        session,
        OpenTicketIn(
            visit_reference=visit_reference, scale_code="SCALE-T1", reentry_justified=True
        ),
    )
    assert again.state == "open"
