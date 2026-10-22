"""Agendamento: onde dói é capacidade finita, concorrência e rastro de reprogramação."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import (
    ERR_YARD_APPOINTMENT_STALE,
    ERR_YARD_DOCK_WINDOW_TAKEN,
    ERR_YARD_PLANT_STOPPAGE,
    ERR_YARD_RESOURCE_EXHAUSTED,
    Conflict,
)
from app.modules.scheduling import service
from app.modules.scheduling.models import Appointment, AppointmentChangeLog, SlotReservation
from app.modules.scheduling.schemas import AppointmentIn, CancelIn, ConfirmIn, RescheduleIn
from app.modules.visits import service as visit_service
from app.modules.visits.schemas import GateInIn, SlotAssignIn

UTC = timezone.utc


def _window(offset_hours: int = 2, minutes: int = 90) -> tuple[datetime, datetime]:
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=offset_hours
    )
    return start, start + timedelta(minutes=minutes)


def _appointment(plate="TST1A01", dock="DOCK-T1", offset=2, resource=None) -> AppointmentIn:
    start, end = _window(offset)
    return AppointmentIn(
        dock_code=dock,
        plate=plate,
        operation_type_code="RECEBIMENTO_GRANEL",
        starts_at=start,
        ends_at=end,
        resource_code=resource,
        actor="teste",
    )


async def test_confirmacao_reserva_vaga_e_consome_no_gate_in(session, fixture_yard):
    appointment = await service.create(session, _appointment())
    appointment_id, reference = appointment.id, appointment.reference
    assert appointment.state == "requested"

    await service.confirm(session, appointment_id, ConfirmIn(version=1, slot_code="T-01"))
    reservation = (
        await session.execute(
            select(SlotReservation).where(SlotReservation.appointment_id == appointment_id)
        )
    ).scalar_one()
    assert reservation.state == "active"

    visit = await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A01",
            driver_document="10000000001",
            operation_type_code="RECEBIMENTO_GRANEL",
            appointment_reference=reference,
        ),
    )
    visit_id = visit.id
    session.expire_all()
    reservation = (
        await session.execute(
            select(SlotReservation).where(SlotReservation.appointment_id == appointment_id)
        )
    ).scalar_one()
    assert reservation.state == "consumed"

    # A vaga reservada é a que o pátio entrega — reservar e ignorar seria teatro.
    await visit_service.assign_slot(session, visit_id, SlotAssignIn())
    slot_code = (
        await session.execute(
            text("SELECT s.code FROM visit v JOIN slot s ON s.id = v.current_slot_id"
                 " WHERE v.id = :id"),
            {"id": visit_id},
        )
    ).scalar_one()
    assert slot_code == "T-01"


async def test_doca_nao_aceita_duas_janelas_sobrepostas(session, fixture_yard):
    first = await service.create(session, _appointment())
    await service.confirm(session, first.id, ConfirmIn(version=1, slot_code="T-01"))

    second = await service.create(session, _appointment(plate="TST1A02"))
    with pytest.raises(Conflict) as exc:
        await service.confirm(session, second.id, ConfirmIn(version=1, slot_code="T-02"))
    assert exc.value.code == ERR_YARD_DOCK_WINDOW_TAKEN


async def test_versao_velha_nao_sobrescreve_em_silencio(session, fixture_yard):
    """Dois programadores no mesmo calendário: o segundo recebe o estado atual, não um 200."""
    appointment = await service.create(session, _appointment())
    await service.confirm(session, appointment.id, ConfirmIn(version=1, slot_code="T-01"))

    start, end = _window(6)
    with pytest.raises(Conflict) as exc:
        await service.reschedule(
            session,
            appointment.id,
            RescheduleIn(starts_at=start, ends_at=end, reason_code="CUSTOMER", version=1),
        )
    assert exc.value.code == ERR_YARD_APPOINTMENT_STALE
    assert exc.value.params["current_version"] == 2


async def test_capacidade_de_recurso_e_finita(session, fixture_yard):
    """MOE-01 tem capacidade 1: a segunda janela concorrente não confirma."""
    await session.execute(
        text(
            "INSERT INTO resource (id, plant_id, code, kind, capacity)"
            " VALUES (gen_random_uuid(), :p, 'MOE-T1', 'hopper', 1)"
        ),
        {"p": fixture_yard["plant"]},
    )
    await session.commit()

    first = await service.create(session, _appointment(resource="MOE-T1"))
    await service.confirm(session, first.id, ConfirmIn(version=1, slot_code="T-01"))

    second = await service.create(
        session, _appointment(plate="TST1A02", dock="DOCK-T2", resource="MOE-T1")
    )
    with pytest.raises(Conflict) as exc:
        await service.confirm(session, second.id, ConfirmIn(version=1, slot_code="T-02"))
    assert exc.value.code == ERR_YARD_RESOURCE_EXHAUSTED


async def test_reprogramacao_exige_motivo_e_registra_impacto(session, fixture_yard):
    appointment = await service.create(session, _appointment())
    await service.confirm(session, appointment.id, ConfirmIn(version=1, slot_code="T-01"))

    conflicting = await service.create(session, _appointment(plate="TST1A02", dock="DOCK-T2"))
    await service.confirm(session, conflicting.id, ConfirmIn(version=1, slot_code="T-02"))

    start, end = _window(2)
    await service.reschedule(
        session,
        appointment.id,
        RescheduleIn(
            starts_at=start + timedelta(minutes=10),
            ends_at=end + timedelta(minutes=10),
            reason_code="PLANT_DELAY",
            version=2,
            actor="programador",
        ),
    )
    logs = (
        await session.execute(
            select(AppointmentChangeLog)
            .where(AppointmentChangeLog.appointment_id == appointment.id)
            .order_by(AppointmentChangeLog.occurred_at.desc())
        )
    ).scalars().all()
    assert logs[0].reason_code == "PLANT_DELAY"
    assert logs[0].to_state == "rescheduled"
    assert logs[0].from_starts_at is not None


async def test_parada_de_planta_fecha_a_janela(session, fixture_yard):
    start, end = _window(3)
    await session.execute(
        text(
            "INSERT INTO plant_stoppage (id, plant_id, reason_code, period)"
            " VALUES (gen_random_uuid(), :p, 'MAINTENANCE', tstzrange(:s, :e))"
        ),
        {"p": fixture_yard["plant"], "s": start - timedelta(hours=1), "e": end + timedelta(hours=1)},
    )
    await session.commit()

    with pytest.raises(Conflict) as exc:
        await service.create(session, _appointment(offset=3))
    assert exc.value.code == ERR_YARD_PLANT_STOPPAGE


async def test_reserva_de_vaga_e_exclusiva_no_tempo(session, fixture_yard):
    """Inserção crua: quem segura duas reservas na mesma vaga é o EXCLUDE."""
    appointment = await service.create(session, _appointment())
    await service.confirm(session, appointment.id, ConfirmIn(version=1, slot_code="T-01"))
    slot_id = next(s["id"] for s in fixture_yard["slots"] if s["code"] == "T-01")
    start, end = _window(2)

    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            insert(SlotReservation),
            [
                {
                    "slot_id": slot_id,
                    "appointment_id": appointment.id,
                    "vehicle_id": fixture_yard["vehicles"][1]["id"],
                    "state": "active",
                    "starts_at": start,
                    "ends_at": end,
                }
            ],
        )
        await session.commit()
    await session.rollback()


async def test_cancelamento_libera_reserva(session, fixture_yard):
    appointment = await service.create(session, _appointment())
    appointment_id = appointment.id
    await service.confirm(session, appointment_id, ConfirmIn(version=1, slot_code="T-01"))
    await service.cancel(
        session, appointment_id, CancelIn(reason_code="CARRIER_REQUEST", version=2)
    )
    session.expire_all()
    reservation = (
        await session.execute(
            select(SlotReservation).where(SlotReservation.appointment_id == appointment_id)
        )
    ).scalar_one()
    assert reservation.state == "released"
    appointment_state = (
        await session.execute(select(Appointment.state).where(Appointment.id == appointment_id))
    ).scalar_one()
    assert appointment_state == "cancelled"


async def test_vaga_reservada_nao_entra_no_sorteio_automatico(session, fixture_yard):
    """Reserva que qualquer um pode ocupar não é reserva.

    A alocação automática pegava a primeira vaga sem ocupação aberta e ignorava as reservas
    ativas: o veículo sem agendamento estacionava na vaga do agendado, e o agendado chegava
    e não tinha onde parar — exatamente o que a reserva existia para evitar.
    """
    from app.modules.yard.models import Slot, SlotOccupancy

    # A vaga que a alocação automática escolheria: primeira livre na ordem de código.
    candidate = (
        await session.execute(
            select(Slot)
            .outerjoin(
                SlotOccupancy,
                (SlotOccupancy.slot_id == Slot.id) & (SlotOccupancy.ended_at.is_(None)),
            )
            .where(Slot.status == "available", SlotOccupancy.id.is_(None))
            .order_by(Slot.code)
            .limit(1)
        )
    ).scalars().one()

    appointment = await service.create(session, _appointment(plate="TST9R00", offset=0))
    await service.confirm(
        session, appointment.id, ConfirmIn(version=1, slot_code=candidate.code)
    )

    visit = await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST9R01",
            driver_document="10000000001",
            operation_type_code="RECEBIMENTO_GRANEL",
        ),
    )
    visit = await visit_service.assign_slot(session, visit.id, SlotAssignIn())
    assert visit.current_slot_id != candidate.id
