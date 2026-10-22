import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.errors import ERR_DUPLICATE, AppError, app_error_handler
from app.core.events import hub
from app.core.security import Role, requires
from app.modules.auth.router import router as auth_router
from app.modules.auth.router import users_router
from app.modules.iot.runtime import runtime as field_runtime
from app.modules.yardconfig.router import plants_read_router
from app.modules.yardconfig.router import router as yardconfig_router
from app.modules.catalog.router import router as catalog_router
from app.modules.gate.router import router as gate_router
from app.modules.integrations.router import router as integrations_router
from app.modules.iot.router import router as iot_router
from app.modules.kpi.router import router as kpi_router
from app.modules.moves.router import dock_router
from app.modules.moves.router import router as moves_router
from app.modules.scheduling.portal import router as portal_router
from app.modules.scheduling.router import router as scheduling_router
from app.modules.tower.router import router as tower_router
from app.modules.visits.router import router as visits_router
from app.modules.weighing.router import router as weighing_router
from app.modules.yard.router import router as yard_router

logging.basicConfig(
    level=settings.log_level,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    if settings.log_json
    else "%(asctime)s %(levelname)-5s %(name)s %(message)s",
)
log = logging.getLogger("yard.api")


async def _audit_production_field() -> None:
    """Em produção, nenhum dispositivo pode continuar em protocolo de simulação.

    Configuração pela metade é o jeito silencioso de "ir para produção" fingindo operar:
    a tela mostra peso, a cancela "abre", e nada disso tocou o campo. Aqui vira erro
    alto no log, com a lista de quem falta configurar.
    """
    from sqlalchemy import text as sql_text

    from app.core.db import SessionLocal

    async with SessionLocal() as session:
        pending = (
            await session.execute(
                sql_text(
                    "SELECT code FROM device WHERE protocol = 'simulator'"
                    " UNION ALL"
                    " SELECT code FROM scale WHERE protocol = 'simulator'"
                )
            )
        ).scalars().all()
    if pending:
        log.error(
            "PRODUÇÃO COM DISPOSITIVO EM SIMULAÇÃO: %s — configure protocolo e endpoint",
            ", ".join(pending[:20]),
        )


async def _ensure_master() -> None:
    """Modo `local`: o admin master de `YARD_MASTER_EMAIL` existe antes da primeira tela."""
    from app.core.db import SessionLocal
    from app.modules.auth.service import ensure_master

    async with SessionLocal() as session:
        created = await ensure_master(session)
    if created:
        log.warning("admin master criado: %s", created)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Em modo `live`, o laço de campo sobe junto da API e cai junto com ela."""
    if settings.auth_mode == "local":
        await _ensure_master()
    if settings.field_mode == "live":
        await field_runtime.start()
        log.info("campo em modo LIVE: conectores de planta ativos")
    else:
        log.warning("campo em modo SIMULADOR — não use assim em produção")
    if settings.is_production:
        # Dentro do lifespan: com `lifespan` definido, o FastAPI ignora `on_event`.
        await _audit_production_field()
    yield
    await field_runtime.stop()


app = FastAPI(
    title="GPlanSiS|YARD API",
    version="1.0.0",
    # /docs aberto é mapa da API para quem estiver na rede da planta.
    # Só em desenvolvimento: numa demonstração pública o mapa da API também é exposição.
    docs_url="/docs" if settings.env == "dev" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.env == "dev" else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(IntegrityError)
async def integrity_handler(_, exc: IntegrityError):
    # Invariante do banco virando código de erro traduzível. O texto do Postgres nunca vaza
    # para o cliente — mas vai para o log, senão o diagnóstico vira adivinhação.
    detail = str(getattr(exc, "orig", exc))
    log.warning("violação de integridade: %s", " ".join(detail.split())[:400])
    for code in (
        "ERR_YARD_AUDIT_IMMUTABLE",
        "ERR_YARD_SLOT_BLOCKED",
        "ex_slot_occupancy_slot",
        "ex_slot_occupancy_vehicle",
        "uq_visit_open_vehicle",
        "ex_appointment_dock",
        "ex_appointment_vehicle",
        "ex_slot_reservation",
        "ERR_YARD_APPOINTMENT_STALE",
        "ERR_YARD_PLANT_STOPPAGE",
        "ERR_YARD_TICKET_IMMUTABLE",
        "uq_weighing_open_visit",
        "uq_move_task_active",
        "ex_dock_visit",
        "ck_visit_hold_segregation",
        "ck_weighing_gross_ge_tare",
        "ERR_AUTH_MASTER_PROTECTED",
        "ck_app_user_master_admin",
    ):
        if code in detail:
            mapped = {
                "ex_slot_occupancy_slot": "ERR_YARD_SLOT_OCCUPIED",
                "ex_slot_occupancy_vehicle": "ERR_YARD_VEHICLE_ALREADY_IN_YARD",
                "uq_visit_open_vehicle": "ERR_YARD_VEHICLE_ALREADY_IN_YARD",
                "ex_appointment_dock": "ERR_YARD_DOCK_WINDOW_TAKEN",
                "ex_appointment_vehicle": "ERR_YARD_DOCK_WINDOW_TAKEN",
                "ex_slot_reservation": "ERR_YARD_SLOT_OCCUPIED",
                "uq_weighing_open_visit": "ERR_YARD_TICKET_CLOSED",
                "uq_move_task_active": "ERR_YARD_MOVE_ALREADY_ACTIVE",
                "ex_dock_visit": "ERR_YARD_DOCK_WINDOW_TAKEN",
                "ck_visit_hold_segregation": "ERR_YARD_HOLD_SEGREGATION",
                "ck_weighing_gross_ge_tare": "ERR_YARD_WEIGHT_TARE_ABOVE_GROSS",
                "ck_app_user_master_admin": "ERR_AUTH_MASTER_PROTECTED",
            }.get(code, code)
            return await app_error_handler(_, AppError(mapped))
    return await app_error_handler(_, AppError(ERR_DUPLICATE))


api = APIRouter(prefix="/api/v1")
api.include_router(auth_router)
api.include_router(users_router)
api.include_router(plants_read_router)
api.include_router(yardconfig_router)
api.include_router(catalog_router)
api.include_router(yard_router)
api.include_router(visits_router)
api.include_router(scheduling_router)
api.include_router(gate_router)
api.include_router(integrations_router)
api.include_router(iot_router)
api.include_router(moves_router)
api.include_router(dock_router)
api.include_router(weighing_router)
api.include_router(tower_router)
api.include_router(kpi_router)
app.include_router(api)
app.include_router(portal_router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness: o processo está de pé. Não toca no banco de propósito."""
    return {
        "status": "ok",
        "env": settings.env,
        "plant": settings.plant_code,
        "field_mode": settings.field_mode,
        "auth_mode": settings.auth_mode,
    }


@app.get("/ready", tags=["ops"])
async def ready():
    """Readiness: só entra no balanceador quem consegue falar com o banco."""
    from sqlalchemy import text as sql_text

    from app.core.db import SessionLocal

    try:
        async with SessionLocal() as session:
            await session.execute(sql_text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503, content={"status": "degraded", "reason": str(exc)[:200]}
        )
    return {"status": "ready"}


@app.websocket("/ws/yard")
async def yard_socket(socket: WebSocket) -> None:
    # Modo `local`: o evento carrega placa, então o canal exige o mesmo token da API.
    # Navegador não manda Authorization em WebSocket; o token vai no subprotocolo
    # (`yard.bearer, <token>`) — cabeçalho, e não query string, para não parar em log
    # de acesso do proxy nem do uvicorn.
    subprotocol = None
    if settings.auth_mode == "local":
        from app.core.db import SessionLocal
        from app.core.errors import AppError as _AppError
        from app.core.security import principal_from_local_token

        offered = [
            p.strip() for p in socket.headers.get("sec-websocket-protocol", "").split(",")
        ]
        token = offered[1] if len(offered) == 2 and offered[0] == "yard.bearer" else ""
        try:
            async with SessionLocal() as session:
                await principal_from_local_token(session, token)
        except _AppError:
            await socket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        subprotocol = "yard.bearer"
    await socket.accept(subprotocol=subprotocol)
    try:
        async for message in hub.subscribe():
            await socket.send_text(message)
    except WebSocketDisconnect:
        return


@app.get("/sse/yard", tags=["ops"], dependencies=[Depends(requires(Role.CONTROLLER, Role.GATE))])
async def yard_sse() -> StreamingResponse:
    """Fallback para rede de planta que bloqueia WebSocket."""

    async def stream():
        async for message in hub.subscribe():
            yield f"data: {message}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
