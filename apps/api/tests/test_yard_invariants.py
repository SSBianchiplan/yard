"""Os invariantes que moram no banco. Se algum destes passar pela aplicação, o banco barra."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import ERR_YARD_SLOT_OCCUPIED, Conflict
from app.modules.visits import service
from app.modules.visits.models import VisitEvent
from app.modules.visits.schemas import GateInIn, SlotAssignIn
from app.modules.yard.models import SlotOccupancy


def _gate_in(plate: str, document: str) -> GateInIn:
    return GateInIn(
        plate=plate,
        driver_document=document,
        operation_type_code="RECEBIMENTO_GRANEL",
        gate_code="GATE-T1",
    )


async def test_duas_visitas_nao_ocupam_a_mesma_vaga(session, fixture_yard):
    first = await service.gate_in(session, _gate_in("TST1A01", "10000000001"))
    await service.assign_slot(session, first.id, SlotAssignIn(slot_code="T-01"))

    second = await service.gate_in(session, _gate_in("TST1A02", "10000000001"))
    with pytest.raises(Conflict) as exc:
        await service.assign_slot(session, second.id, SlotAssignIn(slot_code="T-01"))
    assert exc.value.code == ERR_YARD_SLOT_OCCUPIED


async def test_veiculo_nao_ocupa_duas_vagas(session, fixture_yard, now):
    """Inserção crua, sem passar pelo serviço: quem segura é o EXCLUDE."""
    visit = await service.gate_in(session, _gate_in("TST1A01", "10000000001"))
    await service.assign_slot(session, visit.id, SlotAssignIn(slot_code="T-01"))

    other_slot = next(s for s in fixture_yard["slots"] if s["code"] == "T-02")
    vehicle_id = fixture_yard["vehicles"][0]["id"]
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            insert(SlotOccupancy),
            [
                {
                    "id": uuid.uuid4(),
                    "slot_id": other_slot["id"],
                    "visit_id": visit.id,
                    "vehicle_id": vehicle_id,
                    "started_at": now + timedelta(seconds=5),
                    "ended_at": None,
                }
            ],
        )
        await session.commit()
    await session.rollback()


async def test_evento_de_auditoria_e_append_only(session, fixture_yard):
    visit = await service.gate_in(session, _gate_in("TST1A01", "10000000001"))
    event_id = (
        await session.execute(
            text("SELECT id FROM visit_event WHERE visit_id = :v LIMIT 1"), {"v": visit.id}
        )
    ).scalar_one()

    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            text("UPDATE visit_event SET actor = 'adulterado' WHERE id = :id"), {"id": event_id}
        )
        await session.commit()
    await session.rollback()

    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(text("DELETE FROM visit_event WHERE id = :id"), {"id": event_id})
        await session.commit()
    await session.rollback()

    assert (await session.execute(text("SELECT count(*) FROM visit_event"))).scalar_one() >= 1
    assert VisitEvent.__tablename__ == "visit_event"


async def test_saida_exige_carimbo_de_saida(session, fixture_yard):
    """CHECK ck_visit_departed_has_timestamp: 'departed' sem gate_out_at não existe."""
    visit = await service.gate_in(session, _gate_in("TST1A01", "10000000001"))
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            text("UPDATE visit SET state = 'departed' WHERE id = :id"), {"id": visit.id}
        )
        await session.commit()
    await session.rollback()


async def test_nao_encontrado_por_codigo_devolve_404_traduzivel(session, fixture_yard):
    """Regressão: `code` como parâmetro de erro colidia com o código do próprio erro.

    O efeito era 500 (TypeError) em vez de 404 com código traduzível — em toda rota que
    procura algo por código: vaga, doca, balança, guarita, dispositivo, manobrista.
    """
    from app.core.errors import ERR_NOT_FOUND, NotFound
    from app.modules.moves import service as moves_service

    with pytest.raises(NotFound) as exc:
        await moves_service.queue(session, spotter_code="NAO-EXISTE")
    assert exc.value.code == ERR_NOT_FOUND
    assert exc.value.params == {"entity": "spotter", "code": "NAO-EXISTE"}

    with pytest.raises(NotFound) as exc:
        await service.assign_slot(
            session,
            (await service.gate_in(session, _gate_in("TST1A01", "10000000001"))).id,
            SlotAssignIn(slot_code="VAGA-INEXISTENTE"),
        )
    assert exc.value.params["code"] == "VAGA-INEXISTENTE"
