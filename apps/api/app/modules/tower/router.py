from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires
from app.modules.tower import service
from app.modules.tower.models import AiProposal, BottleneckSignal, HumanDecision
from app.modules.tower.schemas import (
    ApproveIn,
    BottleneckOut,
    DecisionOut,
    ForecastOut,
    ProposalOut,
    RejectIn,
    TowerOverviewOut,
)

router = APIRouter(
    prefix="/control-tower",
    tags=["control-tower"],
    dependencies=[Depends(requires(Role.CONTROLLER, Role.SUPERVISOR))],
)


@router.get("/overview", response_model=TowerOverviewOut)
async def overview(session: AsyncSession = Depends(get_session)) -> TowerOverviewOut:
    """Painel único da torre: fila, ocupação, atraso, risco de demurrage e gargalo."""
    return TowerOverviewOut(**await service.overview(session))


@router.get("/proposals", response_model=list[ProposalOut])
async def list_proposals(
    session: AsyncSession = Depends(get_session),
    state: str | None = Query(default="proposed"),
    limit: int = Query(default=50, le=200),
) -> list[ProposalOut]:
    await service.expire_stale(session)
    stmt = select(AiProposal).order_by(AiProposal.created_at.desc()).limit(limit)
    if state:
        stmt = stmt.where(AiProposal.state == state)
    rows = (await session.execute(stmt)).scalars().all()
    return [ProposalOut.model_validate(row) for row in rows]


@router.post("/proposals/generate", response_model=list[ProposalOut])
async def generate(session: AsyncSession = Depends(get_session)) -> list[ProposalOut]:
    """Roda o agente. Tudo que sai daqui nasce em `proposed` — nada executa sozinho."""
    proposals = await service.generate_proposals(session)
    return [ProposalOut.model_validate(p) for p in proposals]


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
async def approve(
    proposal_id: UUID, data: ApproveIn, session: AsyncSession = Depends(get_session)
) -> ProposalOut:
    return ProposalOut.model_validate(await service.approve(session, proposal_id, data))


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
async def reject(
    proposal_id: UUID, data: RejectIn, session: AsyncSession = Depends(get_session)
) -> ProposalOut:
    return ProposalOut.model_validate(await service.reject(session, proposal_id, data))


@router.post("/proposals/{proposal_id}/execute", response_model=ProposalOut)
async def execute(
    proposal_id: UUID,
    actor: str = Body(embed=True),
    session: AsyncSession = Depends(get_session),
) -> ProposalOut:
    """Executa o que já foi aprovado. Sem aprovação registrada, recusa."""
    return ProposalOut.model_validate(await service.execute(session, proposal_id, actor))


@router.get("/proposals/{proposal_id}/decisions", response_model=list[DecisionOut])
async def decisions(
    proposal_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[DecisionOut]:
    rows = (
        await session.execute(
            select(HumanDecision)
            .where(HumanDecision.proposal_id == proposal_id)
            .order_by(HumanDecision.decided_at)
        )
    ).scalars().all()
    return [DecisionOut.model_validate(row) for row in rows]


@router.get("/bottlenecks", response_model=list[BottleneckOut])
async def bottlenecks(
    session: AsyncSession = Depends(get_session), state: str | None = None
) -> list[BottleneckOut]:
    await service.detect_bottlenecks(session)
    stmt = select(BottleneckSignal).order_by(BottleneckSignal.detected_at.desc()).limit(100)
    if state:
        stmt = stmt.where(BottleneckSignal.state == state)
    rows = (await session.execute(stmt)).scalars().all()
    return [BottleneckOut.model_validate(row) for row in rows]


@router.post("/bottlenecks/{signal_id}/acknowledge", response_model=BottleneckOut)
async def acknowledge(
    signal_id: UUID,
    actor: str = Body(embed=True),
    session: AsyncSession = Depends(get_session),
) -> BottleneckOut:
    return BottleneckOut.model_validate(
        await service.acknowledge_bottleneck(session, signal_id, actor)
    )


@router.get("/forecast/{visit_id}", response_model=ForecastOut)
async def forecast(visit_id: UUID, session: AsyncSession = Depends(get_session)) -> ForecastOut:
    return ForecastOut.model_validate(await service.forecast_release(session, visit_id))
