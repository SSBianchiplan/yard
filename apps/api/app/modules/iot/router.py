from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import Role, requires
from app.core.errors import ERR_NOT_FOUND, NotFound
from app.modules.gate.models import Device
from app.modules.iot import service
from app.modules.iot.models import Signal
from app.modules.iot.schemas import (
    DeviceAvailabilityOut,
    DeviceHealthIn,
    EdgeBatchIn,
    ReadingIn,
    RtlsIn,
    RtlsOut,
    SignalIn,
)

router = APIRouter(
    prefix="/iot",
    tags=["iot"],
    dependencies=[Depends(requires(Role.CONTROLLER, Role.ADMIN))],
)


@router.get("/signals")
async def list_signals(
    session: AsyncSession = Depends(get_session),
    kind: str | None = None,
    device_code: str | None = None,
):
    stmt = select(Signal).order_by(Signal.path)
    if kind:
        stmt = stmt.where(Signal.kind == kind)
    if device_code:
        device = (
            await session.execute(select(Device).where(Device.code == device_code))
        ).scalar_one_or_none()
        if device is None:
            raise NotFound(ERR_NOT_FOUND, entity="device", code=device_code)
        stmt = stmt.where(Signal.device_id == device.id)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "path": row.path,
            "code": row.code,
            "kind": row.kind,
            "data_type": row.data_type,
            "safety_related": row.safety_related,
            "stale_after_seconds": row.stale_after_seconds,
        }
        for row in rows
    ]


@router.post("/signals", status_code=201)
async def create_signal(data: SignalIn, session: AsyncSession = Depends(get_session)):
    device = (
        await session.execute(select(Device).where(Device.code == data.device_code))
    ).scalar_one_or_none()
    if device is None:
        raise NotFound(ERR_NOT_FOUND, entity="device", code=data.device_code)
    signal = Signal(
        device_id=device.id,
        code=data.code,
        path=data.path,
        kind=data.kind,
        data_type=data.data_type,
        unit=data.unit,
        safety_related=data.safety_related,
        stale_after_seconds=data.stale_after_seconds,
        source_address=data.source_address,
    )
    session.add(signal)
    await session.commit()
    return {"id": signal.id, "path": signal.path}


@router.get("/signals/current")
async def current_signals(session: AsyncSession = Depends(get_session)):
    """Último valor de cada sinal, com frescor — o que a torre realmente lê."""
    rows = (
        await session.execute(text("SELECT * FROM signal_current ORDER BY path"))
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/signals/stale")
async def stale(session: AsyncSession = Depends(get_session)):
    return await service.stale_signals(session)


@router.post("/readings")
async def ingest(readings: list[ReadingIn], session: AsyncSession = Depends(get_session)):
    return await service.ingest(session, readings)


@router.post("/edge/sync")
async def edge_sync(data: EdgeBatchIn, session: AsyncSession = Depends(get_session)):
    """Reconciliação ao religar: lote idempotente, ordenado pela hora do campo."""
    return await service.sync_edge(session, data)


@router.get("/devices/availability", response_model=list[DeviceAvailabilityOut])
async def availability(
    session: AsyncSession = Depends(get_session), hours: int = Query(default=24, le=720)
):
    return [DeviceAvailabilityOut(**row) for row in await service.availability(session, hours)]


@router.post("/devices/{device_code}/health")
async def health(
    device_code: str, data: DeviceHealthIn, session: AsyncSession = Depends(get_session)
):
    device = await service.record_health(
        session, device_code, data.status, data.latency_ms, data.error_code
    )
    return {"code": device.code, "status": device.status, "last_seen_at": device.last_seen_at}


@router.get("/devices/{device_code}/permissive")
async def permissive(device_code: str, session: AsyncSession = Depends(get_session)):
    """Permissivo com qualidade. Obsoleto não é permissivo — e a resposta diz isso."""
    value, quality = await service.permissive_for(session, device_code)
    return {"device_code": device_code, "permissive": value, "quality": quality}


@router.post("/rtls", response_model=RtlsOut, status_code=201)
async def rtls(data: RtlsIn, session: AsyncSession = Depends(get_session)):
    """Camada opcional: posição fina. Nenhuma regra depende dela para funcionar."""
    return RtlsOut.model_validate(await service.record_position(session, data))


if settings.simulators_enabled:
    # Em produção esta rota **não é registrada**. Guardar com `if` dentro do handler
    # deixaria o endpoint existindo e documentado no /docs de produção; aqui ele some.
    @router.post("/simulate")
    async def simulate(
        seconds: int = Query(default=1, le=60), session: AsyncSession = Depends(get_session)
    ):
        """Tick de campo falso — desenvolve-se o sistema inteiro sem CLP nenhum."""
        return await service.simulate_field(session, seconds)
