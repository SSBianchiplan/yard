from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires
from app.modules.catalog.models import Vehicle
from app.modules.moves import service
from app.modules.moves.models import Discrepancy, DockVisit, MoveDeviation, MoveTask, Spotter, VisitHold
from app.modules.moves.schemas import (
    ConfirmMoveIn,
    CreateMoveIn,
    DiscrepancyIn,
    DockStageIn,
    DockVisitOut,
    HoldIn,
    HoldOut,
    HoldReleaseIn,
    MoveTaskOut,
    OrderLinkIn,
)
from app.modules.visits.models import Visit
from app.modules.yard.models import Dock, Slot

router = APIRouter(
    prefix="/moves",
    tags=["moves"],
    dependencies=[Depends(requires(Role.SPOTTER, Role.DOCK, Role.CONTROLLER))],
)


async def _to_out(session: AsyncSession, task: MoveTask) -> MoveTaskOut:
    async def code(model, ident):
        if ident is None:
            return None
        return (
            await session.execute(select(model.code).where(model.id == ident))
        ).scalar_one_or_none()

    return MoveTaskOut(
        id=task.id,
        reference=task.reference,
        state=task.state,
        plate=(
            await session.execute(select(Vehicle.plate).where(Vehicle.id == task.vehicle_id))
        ).scalar_one_or_none(),
        visit_id=task.visit_id,
        visit_reference=(
            await session.execute(select(Visit.reference).where(Visit.id == task.visit_id))
        ).scalar_one_or_none(),
        from_slot_code=await code(Slot, task.from_slot_id),
        to_slot_code=await code(Slot, task.to_slot_id),
        to_dock_code=await code(Dock, task.to_dock_id),
        spotter_code=await code(Spotter, task.spotter_id),
        priority_rank=task.priority_rank,
        cost_score=task.cost_score,
        distance_m=task.distance_m,
        sla_deadline=task.sla_deadline,
        queued_at=task.queued_at,
        accepted_at=task.accepted_at,
        confirmed_at=task.confirmed_at,
        confirmation_kind=task.confirmation_kind,
    )


@router.get("/spotters")
async def spotters(session: AsyncSession = Depends(get_session)):
    """Manobristas ativos. O tablet do pátio é compartilhado: quem assume a tarefa
    se identifica na lista, e é esse código que assina a execução."""
    rows = (
        await session.execute(
            select(Spotter).where(Spotter.active.is_(True)).order_by(Spotter.code)
        )
    ).scalars().all()
    return [
        {"code": row.code, "full_name": row.full_name, "shift_code": row.shift_code}
        for row in rows
    ]


@router.get("/queue", response_model=list[MoveTaskOut])
async def queue(
    session: AsyncSession = Depends(get_session), spotter_code: str | None = None
) -> list[MoveTaskOut]:
    """Fila ordenada por custo de movimento — o próximo é o mais barato, não o mais velho."""
    tasks = await service.queue(session, spotter_code)
    return [await _to_out(session, task) for task in tasks]


@router.post("/tasks", response_model=MoveTaskOut, status_code=201)
async def create_task(data: CreateMoveIn, session: AsyncSession = Depends(get_session)):
    task = await service.create_task(session, data)
    return await _to_out(session, task)


@router.post("/tasks/{task_id}/assign", response_model=MoveTaskOut)
async def assign(
    task_id: UUID, spotter_code: str = Body(embed=True), session: AsyncSession = Depends(get_session)
):
    task = await service.assign(session, task_id, spotter_code)
    return await _to_out(session, task)


@router.post("/tasks/{task_id}/accept", response_model=MoveTaskOut)
async def accept(
    task_id: UUID, spotter_code: str = Body(embed=True), session: AsyncSession = Depends(get_session)
):
    task = await service.accept(session, task_id, spotter_code)
    return await _to_out(session, task)


@router.post("/tasks/{task_id}/start", response_model=MoveTaskOut)
async def start(task_id: UUID, session: AsyncSession = Depends(get_session)):
    task = await service.start(session, task_id)
    return await _to_out(session, task)


@router.post("/tasks/{task_id}/confirm", response_model=MoveTaskOut)
async def confirm(
    task_id: UUID, data: ConfirmMoveIn, session: AsyncSession = Depends(get_session)
):
    task = await service.confirm(session, task_id, data)
    return await _to_out(session, task)


@router.post("/tasks/{task_id}/cancel", response_model=MoveTaskOut)
async def cancel(
    task_id: UUID,
    reason_code: str = Body(embed=True),
    actor: str = Body(default="web", embed=True),
    session: AsyncSession = Depends(get_session),
) -> MoveTaskOut:
    """Cancela a tarefa com motivo — tarefa que morre em silêncio some do KPI."""
    task = await service.cancel(session, task_id, reason_code, actor)
    return await _to_out(session, task)


@router.post("/sync")
async def sync(events: list[dict], session: AsyncSession = Depends(get_session)):
    """Lote do PWA offline. Idempotente por `task_id` + estado — reenviar é seguro."""
    return await service.sync_offline(session, events)


@router.get("/deviations")
async def deviations(
    session: AsyncSession = Depends(get_session), limit: int = Query(default=100, le=500)
):
    rows = (
        await session.execute(
            select(MoveDeviation).order_by(MoveDeviation.detected_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "detected_at": row.detected_at,
            "vehicle_id": row.vehicle_id,
            "expected_slot_id": row.expected_slot_id,
            "actual_slot_id": row.actual_slot_id,
            "state": row.state,
        }
        for row in rows
    ]


# ----------------------------- doca -----------------------------

dock_router = APIRouter(prefix="/docks", tags=["docks"])


@dock_router.post("/visits/{visit_id}/stage", response_model=DockVisitOut)
async def stage(visit_id: UUID, data: DockStageIn, session: AsyncSession = Depends(get_session)):
    dock_visit = await service.dock_stage(session, visit_id, data)
    return DockVisitOut.model_validate(dock_visit)


@dock_router.get("/visits/{visit_id}", response_model=list[DockVisitOut])
async def dock_visits(visit_id: UUID, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(DockVisit)
            .where(DockVisit.visit_id == visit_id)
            .order_by(DockVisit.arrived_at.desc())
        )
    ).scalars().all()
    return [DockVisitOut.model_validate(row) for row in rows]


@dock_router.post("/dock-visits/{dock_visit_id}/discrepancies", status_code=201)
async def report_discrepancy(
    dock_visit_id: UUID, data: DiscrepancyIn, session: AsyncSession = Depends(get_session)
):
    discrepancy = await service.report_discrepancy(session, dock_visit_id, data)
    return {"id": discrepancy.id, "kind": discrepancy.kind, "state": discrepancy.state}


@dock_router.get("/dock-visits/{dock_visit_id}/discrepancies")
async def list_discrepancies(
    dock_visit_id: UUID, session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.execute(
            select(Discrepancy).where(Discrepancy.dock_visit_id == dock_visit_id)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "state": row.state,
            "evidence_ref": row.evidence_ref,
            "reported_by": row.reported_by,
            "reported_at": row.reported_at,
        }
        for row in rows
    ]


@dock_router.post("/visits/{visit_id}/holds", response_model=HoldOut, status_code=201)
async def open_hold(visit_id: UUID, data: HoldIn, session: AsyncSession = Depends(get_session)):
    hold = await service.open_hold(session, visit_id, data)
    return HoldOut.model_validate(hold)


@dock_router.get("/visits/{visit_id}/holds", response_model=list[HoldOut])
async def list_holds(visit_id: UUID, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(VisitHold).where(VisitHold.visit_id == visit_id).order_by(VisitHold.opened_at)
        )
    ).scalars().all()
    return [HoldOut.model_validate(row) for row in rows]


@dock_router.post("/holds/{hold_id}/release", response_model=HoldOut)
async def release_hold(
    hold_id: UUID, data: HoldReleaseIn, session: AsyncSession = Depends(get_session)
):
    hold = await service.release_hold(session, hold_id, data)
    return HoldOut.model_validate(hold)


@dock_router.post("/visits/{visit_id}/orders", status_code=201)
async def link_order(visit_id: UUID, data: OrderLinkIn, session: AsyncSession = Depends(get_session)):
    link = await service.link_order(session, visit_id, data)
    return {"id": link.id, "kind": link.kind, "external_id": link.external_id}
