"""Camada OT: qualidade do dado, idempotência do edge e permissivo que não mente."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import insert, select, text

from app.core.errors import ERR_YARD_COMMAND_DENIED_BY_PLC, Conflict
from app.modules.gate import service as gate_service
from app.modules.gate.models import Device
from app.modules.gate.schemas import CommandIn
from app.modules.iot import service
from app.modules.iot.models import EdgeBatch, Signal, SignalReading
from app.modules.iot.schemas import EdgeBatchIn, ReadingIn, RtlsIn


async def _device_with_permissive(session, fixture_yard, *, code="BAR-T1", stale_after=30):
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
                "protocol": "mqtt_sparkplug",
                "status": "online",
            }
        ],
    )
    signal_id = uuid.uuid4()
    await session.execute(
        insert(Signal),
        [
            {
                "id": signal_id,
                "device_id": device_id,
                "code": "PERMISSIVE",
                "path": f"plant-01/gate/{code}/permissive",
                "kind": "permissive",
                "data_type": "bool",
                "safety_related": True,
                "stale_after_seconds": stale_after,
            }
        ],
    )
    await session.commit()
    return device_id, signal_id


async def _write(session, signal_id, device_id, *, value: bool, age_seconds: int = 0):
    await session.execute(
        insert(SignalReading),
        [
            {
                "id": uuid.uuid4(),
                "occurred_at": service.now() - timedelta(seconds=age_seconds),
                "received_at": service.now(),
                "signal_id": signal_id,
                "device_id": device_id,
                "value_bool": value,
                "quality": "good",
            }
        ],
    )
    await session.commit()


async def test_permissivo_fresco_libera_e_obsoleto_nao(session, fixture_yard):
    """Permissivo obsoleto diz o que era verdade há dois minutos. Não serve para cancela."""
    device_id, signal_id = await _device_with_permissive(session, fixture_yard, stale_after=10)

    await _write(session, signal_id, device_id, value=True, age_seconds=0)
    value, quality = await service.permissive_for(session, "BAR-T1")
    assert (value, quality) == (True, "good")

    # Mesma leitura, agora velha demais para o limite do sinal.
    await session.execute(text("DELETE FROM signal_reading"))
    await session.commit()
    await _write(session, signal_id, device_id, value=True, age_seconds=120)
    value, quality = await service.permissive_for(session, "BAR-T1")
    assert value is False and quality == "stale"


async def test_comando_recusado_quando_permissivo_esta_obsoleto(session, fixture_yard):
    device_id, signal_id = await _device_with_permissive(session, fixture_yard, stale_after=5)
    await _write(session, signal_id, device_id, value=True, age_seconds=300)

    with pytest.raises(Conflict) as exc:
        await gate_service.command(
            session,
            CommandIn(device_code="BAR-T1", action="open_barrier", authorized_by="guarda.01"),
        )
    assert exc.value.code == ERR_YARD_COMMAND_DENIED_BY_PLC

    state = (
        await session.execute(
            text("SELECT state, failure_code FROM access_command ORDER BY requested_at DESC LIMIT 1")
        )
    ).mappings().one()
    assert state["state"] == "denied_by_plc"


async def test_evento_de_campo_repetido_nao_duplica(session, fixture_yard):
    """Mesma tag, mesma hora, mesmo dispositivo: entra uma vez só."""
    device_id, signal_id = await _device_with_permissive(session, fixture_yard)
    path = f"plant-01/gate/BAR-T1/permissive"
    moment = service.now()

    first = await service.ingest(
        session, [ReadingIn(path=path, occurred_at=moment, value_bool=True)]
    )
    second = await service.ingest(
        session, [ReadingIn(path=path, occurred_at=moment, value_bool=True)]
    )
    assert first["applied"] == 1
    assert second["applied"] == 0 and second["skipped"] == 1

    total = (
        await session.execute(text("SELECT count(*) FROM signal_reading"))
    ).scalar_one()
    assert total == 1


async def test_lote_do_edge_e_idempotente_e_ordena_pelo_campo(session, fixture_yard):
    """Rede volta, o edge despeja o buffer. Reenviar o lote não pode inventar história."""
    device_id, signal_id = await _device_with_permissive(session, fixture_yard)
    path = "plant-01/gate/BAR-T1/permissive"
    base = service.now()

    batch = EdgeBatchIn(
        batch_key="edge-01/2026-09-20T12:00:00Z",
        edge_node="edge-01",
        readings=[
            ReadingIn(path=path, occurred_at=base - timedelta(seconds=10), value_bool=False),
            ReadingIn(path=path, occurred_at=base - timedelta(seconds=30), value_bool=True),
            ReadingIn(path=path, occurred_at=base - timedelta(seconds=20), value_bool=False),
        ],
    )
    result = await service.sync_edge(session, batch)
    assert result["applied"] == 3 and result["duplicate"] == 0

    repeat = await service.sync_edge(session, batch)
    assert repeat["duplicate"] == 1
    total = (await session.execute(text("SELECT count(*) FROM signal_reading"))).scalar_one()
    assert total == 3

    stored = (
        await session.execute(select(EdgeBatch).where(EdgeBatch.batch_key == batch.batch_key))
    ).scalar_one()
    # A janela do lote é a hora do campo, não a da chegada.
    assert stored.oldest_event_at < stored.newest_event_at


async def test_dispositivo_offline_derruba_qualidade_do_sinal(session, fixture_yard):
    device_id, signal_id = await _device_with_permissive(session, fixture_yard)
    await _write(session, signal_id, device_id, value=True)

    await service.record_health(session, "BAR-T1", "offline", error_code="LINK_DOWN")
    value, quality = await service.permissive_for(session, "BAR-T1")
    assert value is False and quality == "no_comm"

    stale = await service.stale_signals(session)
    assert any(row["device_code"] == "BAR-T1" for row in stale)


async def test_disponibilidade_por_dispositivo(session, fixture_yard):
    await _device_with_permissive(session, fixture_yard)
    await service.record_health(session, "BAR-T1", "online", latency_ms=12)
    await service.record_health(session, "BAR-T1", "degraded", error_code="JITTER")
    await service.record_health(session, "BAR-T1", "online", latency_ms=15)

    rows = await service.availability(session, hours=24)
    row = next(r for r in rows if r["code"] == "BAR-T1")
    assert 0 < float(row["availability_pct"]) < 100
    assert row["incidents"] == 1


async def test_rtls_e_camada_opcional(session, fixture_yard):
    """RTLS entra como precisão extra: sem ele o pátio segue, com ele a vaga é inferida."""
    slot = next(s for s in fixture_yard["slots"] if s["code"] == "T-01")
    await session.execute(
        text("UPDATE slot SET x = 100, y = 200, width = 20, height = 40 WHERE id = :id"),
        {"id": slot["id"]},
    )
    await session.commit()

    position = await service.record_position(
        session,
        RtlsIn(
            technology="uwb",
            x=110,
            y=220,
            vehicle_id=fixture_yard["vehicles"][0]["id"],
            accuracy_m=0.3,
        ),
    )
    assert position.slot_id == slot["id"]

    # Nenhuma regra depende de RTLS: o gate-in continua funcionando sem posição nenhuma.
    from app.modules.visits import service as visit_service
    from app.modules.visits.schemas import GateInIn

    visit = await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A02",
            driver_document="10000000001",
            operation_type_code="RECEBIMENTO_GRANEL",
        ),
    )
    assert visit.state == "at_gate_in"
