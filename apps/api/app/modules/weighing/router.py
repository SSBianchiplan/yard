from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import Principal, Role, current_principal, requires, with_actor
from app.core.errors import ERR_NOT_FOUND, Forbidden, NotFound
from app.modules.catalog.models import Vehicle
from app.modules.visits.models import Visit
from app.modules.weighing import service
from app.modules.weighing.drivers import SimulatorScaleDriver, driver_for
from app.modules.weighing.models import WeighingCapture, WeighingTicket
from app.modules.weighing.schemas import (
    CaptureIn,
    CaptureOut,
    CloseTicketIn,
    LiveReadingOut,
    OpenTicketIn,
    ReprintIn,
    TicketOut,
)
from app.modules.yard.models import Scale

router = APIRouter(
    prefix="/weighing",
    tags=["weighing"],
    dependencies=[Depends(requires(Role.SCALE, Role.SUPERVISOR))],
)


async def _to_out(session: AsyncSession, ticket: WeighingTicket) -> TicketOut:
    plate = (
        await session.execute(select(Vehicle.plate).where(Vehicle.id == ticket.vehicle_id))
    ).scalar_one_or_none()
    visit_reference = (
        await session.execute(select(Visit.reference).where(Visit.id == ticket.visit_id))
    ).scalar_one_or_none()
    scale_code = (
        await session.execute(select(Scale.code).where(Scale.id == ticket.scale_id))
    ).scalar_one_or_none()
    captures = (
        await session.execute(
            select(WeighingCapture)
            .where(WeighingCapture.ticket_id == ticket.id)
            .order_by(WeighingCapture.occurred_at)
        )
    ).scalars().all()

    within = None
    if ticket.divergence_pct is not None:
        within = abs(ticket.divergence_pct) <= ticket.tolerance_pct

    return TicketOut(
        id=ticket.id,
        reference=ticket.reference,
        state=ticket.state,
        visit_reference=visit_reference,
        plate=plate,
        scale_code=scale_code,
        mode=ticket.mode,
        gross_kg=ticket.gross_kg,
        tare_kg=ticket.tare_kg,
        net_kg=ticket.net_kg,
        tare_source=ticket.tare_source,
        document_number=ticket.document_number,
        document_net_kg=ticket.document_net_kg,
        divergence_kg=ticket.divergence_kg,
        divergence_pct=ticket.divergence_pct,
        tolerance_pct=ticket.tolerance_pct,
        within_tolerance=within,
        tare_drift_pct=await service.tare_drift(session, ticket),
        source=ticket.source,
        operator=ticket.operator,
        integrity_hash=ticket.integrity_hash,
        reprint_count=ticket.reprint_count,
        closed_at=ticket.closed_at,
        captures=[CaptureOut.model_validate(c) for c in captures],
    )


@router.get("/scales/{scale_code}/live", response_model=LiveReadingOut)
async def live(scale_code: str, session: AsyncSession = Depends(get_session)) -> LiveReadingOut:
    """Leitura corrente do indicador. Qualidade vem junto: peso sem frescor não decide nada."""
    sample = await service.live_reading(session, scale_code)
    return LiveReadingOut(
        scale_code=scale_code,
        weight_kg=sample.weight_kg,
        stable=sample.stable,
        quality=sample.quality,
        occurred_at=sample.occurred_at,
    )


@router.get("/tickets", response_model=list[TicketOut])
async def list_tickets(
    session: AsyncSession = Depends(get_session),
    state: list[str] | None = Query(default=None),
    visit_reference: str | None = None,
    limit: int = Query(default=200, le=1000),
) -> list[TicketOut]:
    stmt = select(WeighingTicket).order_by(WeighingTicket.created_at.desc()).limit(limit)
    if state:
        stmt = stmt.where(WeighingTicket.state.in_(state))
    if visit_reference:
        stmt = stmt.join(Visit, Visit.id == WeighingTicket.visit_id).where(
            Visit.reference == visit_reference
        )
    tickets = (await session.execute(stmt)).scalars().all()
    return [await _to_out(session, ticket) for ticket in tickets]


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: UUID, session: AsyncSession = Depends(get_session)) -> TicketOut:
    ticket = (
        await session.execute(select(WeighingTicket).where(WeighingTicket.id == ticket_id))
    ).scalar_one_or_none()
    if ticket is None:
        raise NotFound(ERR_NOT_FOUND, entity="weighing_ticket", id=str(ticket_id))
    return await _to_out(session, ticket)


@router.post("/tickets", response_model=TicketOut, status_code=201)
async def open_ticket(
    data: OpenTicketIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(current_principal),
):
    ticket = await service.open_ticket(session, with_actor(data, principal, "operator"))
    return await _to_out(session, ticket)


@router.post("/tickets/{ticket_id}/capture", response_model=TicketOut)
async def capture(
    ticket_id: UUID,
    data: CaptureIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(current_principal),
) -> TicketOut:
    ticket = await service.capture(session, ticket_id, with_actor(data, principal, "operator"))
    return await _to_out(session, ticket)


@router.post("/tickets/{ticket_id}/close", response_model=TicketOut)
async def close_ticket(
    ticket_id: UUID, data: CloseTicketIn, session: AsyncSession = Depends(get_session)
) -> TicketOut:
    ticket = await service.close_ticket(session, ticket_id, data)
    return await _to_out(session, ticket)


@router.post("/tickets/{ticket_id}/reprint", response_model=TicketOut)
async def reprint(
    ticket_id: UUID,
    data: ReprintIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(current_principal),
) -> TicketOut:
    ticket = await service.reprint(session, ticket_id, with_actor(data, principal, "actor"))
    return await _to_out(session, ticket)


if settings.simulators_enabled:

    @router.post("/scales/{scale_code}/simulate", response_model=LiveReadingOut)
    async def simulate(
        scale_code: str,
        target_kg: int,
        settle: bool = True,
        session: AsyncSession = Depends(get_session),
    ) -> LiveReadingOut:
        """Coloca a balança simulada num peso alvo — o caminhão "sobe e desce" da
        plataforma sem hardware. Rota inexistente em produção.
        """
        scale = (
            await session.execute(select(Scale).where(Scale.code == scale_code))
        ).scalar_one_or_none()
        if scale is None:
            raise NotFound(ERR_NOT_FOUND, entity="scale", code=scale_code)

        driver = driver_for(scale.code, scale.protocol, scale.endpoint)
        if not isinstance(driver, SimulatorScaleDriver):
            raise Forbidden("ERR_FORBIDDEN", scope="simulator", protocol=scale.protocol)

        driver.set_target(target_kg)
        sample = await driver.read()
        if settle:
            for _ in range(14):
                sample = await driver.read()
                if sample.stable:
                    break
        return LiveReadingOut(
            scale_code=scale_code,
            weight_kg=sample.weight_kg,
            stable=sample.stable,
            quality=sample.quality,
            occurred_at=sample.occurred_at,
        )
