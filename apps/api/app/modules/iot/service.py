"""Camada OT: ingestão de campo, saúde de dispositivo e operação degradada.

Três coisas que este módulo garante e que normalmente se descobre tarde:
  1. **qualidade é dado**: `good | stale | invalid | no_comm` anda junto do valor, sempre;
  2. **a rede vai cair**: o edge guarda, reenvia, e a reconciliação é idempotente;
  3. **permissivo obsoleto não é permissivo**: sinal velho nunca autoriza atuação.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_NOT_FOUND, NotFound
from app.core.events import hub
from app.modules.gate.models import Device
from app.modules.iot.models import DeviceHealth, EdgeBatch, RtlsPosition, Signal, SignalReading
from app.modules.iot.schemas import EdgeBatchIn, ReadingIn, RtlsIn
from app.modules.yard.models import Slot


def now() -> datetime:
    return datetime.now(timezone.utc)


async def _one(session: AsyncSession, stmt, entity: str, **params: Any):
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, **params)
    return obj


async def ingest(session: AsyncSession, readings: list[ReadingIn], batch_id: UUID | None = None):
    """Grava leituras de campo. Conflito de chave = evento repetido, e repetido é ignorado.

    Aceitar o mesmo evento duas vezes é o jeito clássico de inventar produção que não
    existiu; `ON CONFLICT DO NOTHING` sobre (sinal, hora, dispositivo) resolve isso no banco.
    """
    applied = skipped = 0
    for reading in readings:
        signal = (
            await session.execute(select(Signal).where(Signal.path == reading.path))
        ).scalar_one_or_none()
        if signal is None:
            skipped += 1
            continue
        result = await session.execute(
            pg_insert(SignalReading)
            .values(
                id=uuid4(),
                occurred_at=reading.occurred_at,
                received_at=now(),
                signal_id=signal.id,
                device_id=signal.device_id,
                value_bool=reading.value_bool,
                value_num=reading.value_num,
                value_text=reading.value_text,
                quality=reading.quality,
                sequence_number=reading.sequence_number,
                batch_id=batch_id,
            )
            .on_conflict_do_nothing(
                index_elements=["signal_id", "occurred_at", "device_id"]
            )
        )
        if result.rowcount:
            applied += 1
        else:
            skipped += 1
    await session.commit()
    return {"applied": applied, "skipped": skipped}


async def sync_edge(session: AsyncSession, data: EdgeBatchIn) -> dict[str, int]:
    """Reconciliação do buffer local ao religar a rede.

    O lote inteiro é idempotente pela chave; a ordem cronológica é reconstruída pelo
    `occurred_at` do campo, não pela hora em que o pacote chegou.
    """
    existing = (
        await session.execute(select(EdgeBatch).where(EdgeBatch.batch_key == data.batch_key))
    ).scalar_one_or_none()
    if existing is not None:
        # Lote já processado: devolve o mesmo resultado, sem reprocessar nada.
        return {
            "applied": existing.applied_count,
            "skipped": existing.skipped_count,
            "duplicate": 1,
        }

    ordered = sorted(data.readings, key=lambda r: r.occurred_at)
    batch = EdgeBatch(
        batch_key=data.batch_key,
        edge_node=data.edge_node,
        received_at=now(),
        event_count=len(ordered),
        oldest_event_at=ordered[0].occurred_at if ordered else None,
        newest_event_at=ordered[-1].occurred_at if ordered else None,
    )
    session.add(batch)
    await session.flush()

    result = await ingest(session, ordered, batch_id=batch.id)
    batch.applied_count = result["applied"]
    batch.skipped_count = result["skipped"]
    await session.commit()
    await hub.publish(
        "yard.edge.reconciled",
        {"edge_node": data.edge_node, "applied": result["applied"]},
    )
    return {**result, "duplicate": 0}


async def read_signal(session: AsyncSession, path: str) -> dict[str, Any]:
    """Lê um sinal com qualidade calculada — a view faz o trabalho de decidir o frescor."""
    row = (
        await session.execute(
            text("SELECT * FROM signal_current WHERE path = :path"), {"path": path}
        )
    ).mappings().first()
    if row is None:
        raise NotFound(ERR_NOT_FOUND, entity="signal", path=path)
    return dict(row)


async def permissive_for(session: AsyncSession, device_code: str) -> tuple[bool, str]:
    """Permissivo do CLP para um dispositivo, com qualidade.

    Regra dura: qualidade diferente de `good` **não** libera. Um permissivo obsoleto diz
    o que era verdade há dois minutos — e dois minutos é uma eternidade para uma cancela.
    """
    rows = (
        await session.execute(
            text(
                "SELECT value_bool, quality FROM signal_current"
                " WHERE device_code = :code AND kind = 'permissive'"
            ),
            {"code": device_code},
        )
    ).mappings().all()
    if not rows:
        return False, "no_comm"
    if any(row["quality"] != "good" for row in rows):
        return False, next(row["quality"] for row in rows if row["quality"] != "good")
    return all(bool(row["value_bool"]) for row in rows), "good"


async def record_health(
    session: AsyncSession, device_code: str, status: str, latency_ms: int | None = None,
    error_code: str | None = None,
) -> Device:
    device = await _one(
        session, select(Device).where(Device.code == device_code), entity="device", code=device_code
    )
    session.add(
        DeviceHealth(
            occurred_at=now(),
            device_id=device.id,
            status=status,
            latency_ms=latency_ms,
            error_code=error_code,
        )
    )
    device.status = status
    device.last_seen_at = now()
    await session.commit()
    if status != "online":
        await hub.publish("yard.device.degraded", {"device": device.code, "status": status})
    return device


async def availability(session: AsyncSession, hours: int = 24) -> list[dict[str, Any]]:
    """Disponibilidade por dispositivo na janela — KPI de campo, não impressão."""
    rows = (
        await session.execute(
            text(
                """
                SELECT d.code,
                       d.kind,
                       d.status,
                       d.last_seen_at,
                       COALESCE(
                           100.0 * count(*) FILTER (WHERE h.status = 'online')
                           / NULLIF(count(h.*), 0), 100.0) AS availability_pct,
                       count(h.*) FILTER (WHERE h.status <> 'online') AS incidents
                  FROM device d
                  LEFT JOIN device_health h
                    ON h.device_id = d.id
                   AND h.occurred_at > now() - make_interval(hours => :hours)
                 GROUP BY d.code, d.kind, d.status, d.last_seen_at
                 ORDER BY availability_pct, d.code
                """
            ),
            {"hours": hours},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def record_position(session: AsyncSession, data: RtlsIn) -> RtlsPosition:
    """RTLS entra como camada de precisão. Se sumir, o pátio continua operando igual."""
    slot_id = None
    if data.slot_code:
        slot = (
            await session.execute(select(Slot).where(Slot.code == data.slot_code))
        ).scalar_one_or_none()
        slot_id = slot.id if slot else None
    elif data.x is not None and data.y is not None:
        # Sem vaga informada, resolve pela geometria do mapa — aproximação boa o bastante.
        slot = (
            await session.execute(
                text(
                    "SELECT id FROM slot"
                    " WHERE :x BETWEEN x AND x + width AND :y BETWEEN y AND y + height"
                    " LIMIT 1"
                ),
                {"x": data.x, "y": data.y},
            )
        ).scalar_one_or_none()
        slot_id = slot

    position = RtlsPosition(
        occurred_at=data.occurred_at or now(),
        vehicle_id=data.vehicle_id,
        asset_tag=data.asset_tag,
        technology=data.technology,
        x=data.x,
        y=data.y,
        accuracy_m=data.accuracy_m,
        slot_id=slot_id,
        quality=data.quality,
    )
    session.add(position)
    await session.commit()
    return position


async def stale_signals(session: AsyncSession) -> list[dict[str, Any]]:
    """Sinais que pararam de chegar. É a lista que a torre precisa ver antes de confiar."""
    rows = (
        await session.execute(
            text("SELECT path, device_code, quality, occurred_at FROM signal_current"
                 " WHERE quality <> 'good' ORDER BY occurred_at")
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def simulate_field(session: AsyncSession, seconds: int = 1) -> dict[str, int]:
    """Gera um tick de campo para todos os sinais — o pátio 'vivo' sem hardware."""
    import random

    signals = (await session.execute(select(Signal))).scalars().all()
    readings: list[ReadingIn] = []
    for signal in signals:
        occurred = now() - timedelta(seconds=random.randint(0, seconds))
        if signal.data_type == "bool":
            value = random.random() > (0.03 if signal.kind == "permissive" else 0.2)
            readings.append(
                ReadingIn(path=signal.path, occurred_at=occurred, value_bool=value)
            )
        else:
            readings.append(
                ReadingIn(
                    path=signal.path,
                    occurred_at=occurred,
                    value_num=round(random.uniform(0, 100), 2),
                )
            )
    return await ingest(session, readings)
