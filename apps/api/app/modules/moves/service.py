"""Movimentação e doca.

Duas ideias sustentam este módulo:
  1. sequenciar por **custo de movimento** (distância real, congestionamento, janela, SLA),
     não por ordem de chegada — pátio grande pune quem ignora distância;
  2. confirmar por **leitura** (QR da vaga, RTLS, foto), não por botão "concluído" —
     botão digitado confirma intenção, leitura confirma fato.
"""

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_NOT_FOUND,
    ERR_YARD_DISCREPANCY_NEEDS_EVIDENCE,
    ERR_YARD_DOCK_STAGE_INVALID,
    ERR_YARD_EXIT_BLOCKED_BY_PENDENCY,
    ERR_YARD_HOLD_SEGREGATION,
    ERR_YARD_INVALID_TRANSITION,
    ERR_YARD_MOVE_ALREADY_ACTIVE,
    ERR_YARD_MOVE_CONFIRMATION_REQUIRED,
    ERR_YARD_MOVE_WRONG_SLOT,
    Conflict,
    NotFound,
)
from app.core.events import hub
from app.modules.moves.models import (
    Discrepancy,
    DockVisit,
    MoveDeviation,
    MoveTask,
    OrderLink,
    Spotter,
    VisitHold,
)
from app.modules.moves.schemas import (
    ConfirmMoveIn,
    CreateMoveIn,
    DiscrepancyIn,
    DockStageIn,
    HoldIn,
    HoldReleaseIn,
    OrderLinkIn,
)
from app.modules.visits.models import Visit
from app.modules.yard.models import Dock, Slot, SlotOccupancy

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "proposed": ("queued", "cancelled"),
    # O manobrista pode puxar da fila e aceitar num ato só — é assim que funciona
    # no PWA; exigir atribuição prévia inventaria burocracia que o pátio não tem.
    "queued": ("assigned", "accepted", "cancelled"),
    "assigned": ("accepted", "queued", "cancelled"),
    "accepted": ("in_progress", "cancelled"),
    # Manobra em execução também se cancela: o pátio muda no meio do caminho.
    "in_progress": ("confirmed", "failed", "cancelled"),
    "confirmed": (),
    "cancelled": (),
    "failed": ("queued",),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


async def _one(session: AsyncSession, stmt, entity: str, **params: Any):
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, **params)
    return obj


def _distance(origin: Slot | Dock | None, target: Slot | Dock | None) -> Decimal:
    """Distância entre posições no mapa, em metros.

    Euclidiana é aproximação honesta para a Fatia 5; a rota real (com sentido de tráfego
    e congestionamento) entra junto do mapa de vias, na Fatia 7.
    """
    if origin is None or target is None:
        return Decimal("0")
    dx = float(target.x) - float(origin.x)
    dy = float(target.y) - float(origin.y)
    return Decimal(str(round(math.hypot(dx, dy), 2)))


def _cost(distance_m: Decimal, priority_rank: int, sla_deadline: datetime | None) -> Decimal:
    """Custo do movimento: distância + urgência. Menor custo é executado antes.

    SLA estourando domina a distância — de propósito: caminhão parado custa mais caro
    que manobrista andando.
    """
    cost = float(distance_m) / 10
    cost += priority_rank / 100
    if sla_deadline is not None:
        minutes_left = (sla_deadline - now()).total_seconds() / 60
        cost -= max(0.0, 240 - minutes_left) / 4
    return Decimal(str(round(cost, 2)))


async def create_task(session: AsyncSession, data: CreateMoveIn) -> MoveTask:
    if data.client_event_id:
        existing = (
            await session.execute(
                select(MoveTask).where(MoveTask.client_event_id == data.client_event_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing  # idempotente: o PWA pode reenviar à vontade

    visit = await _one(
        session,
        select(Visit).where(Visit.reference == data.visit_reference),
        entity="visit",
        reference=data.visit_reference,
    )
    # Manobrar quem ainda está na guarita não existe: o veículo nem entrou.
    if visit.state not in ("in_yard", "at_dock"):
        raise Conflict(
            ERR_YARD_INVALID_TRANSITION, from_state=visit.state, to_state="move_task"
        )

    active = (
        await session.execute(
            select(MoveTask).where(
                MoveTask.vehicle_id == visit.vehicle_id,
                MoveTask.state.in_(("queued", "assigned", "accepted", "in_progress")),
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        raise Conflict(ERR_YARD_MOVE_ALREADY_ACTIVE, reference=active.reference)

    origin = None
    if visit.current_slot_id:
        origin = (
            await session.execute(select(Slot).where(Slot.id == visit.current_slot_id))
        ).scalar_one_or_none()

    to_slot = to_dock = None
    if data.to_slot_code:
        to_slot = await _one(
            session,
            select(Slot).where(Slot.code == data.to_slot_code),
            entity="slot",
            code=data.to_slot_code,
        )
    if data.to_dock_code:
        to_dock = await _one(
            session,
            select(Dock).where(Dock.code == data.to_dock_code),
            entity="dock",
            code=data.to_dock_code,
        )

    distance = _distance(origin, to_slot or to_dock)
    deadline = data.sla_deadline or (now() + timedelta(minutes=data.sla_minutes))
    seq = (await session.execute(text("SELECT nextval('move_task_seq')"))).scalar_one()

    task = MoveTask(
        plant_id=visit.plant_id,
        reference=f"MOV-{date.today().year}-{seq:06d}",
        state="queued",
        visit_id=visit.id,
        vehicle_id=visit.vehicle_id,
        from_slot_id=visit.current_slot_id,
        from_dock_id=visit.current_dock_id,
        to_slot_id=to_slot.id if to_slot else None,
        to_dock_id=to_dock.id if to_dock else None,
        priority_rank=data.priority_rank,
        distance_m=distance,
        cost_score=_cost(distance, data.priority_rank, deadline),
        sla_deadline=deadline,
        queued_at=now(),
        client_event_id=data.client_event_id,
    )
    session.add(task)
    await session.commit()
    await hub.publish("yard.move.queued", {"reference": task.reference, "cost": str(task.cost_score)})
    return task


def _transition(task: MoveTask, target: str) -> str:
    if target not in TRANSITIONS[task.state]:
        raise Conflict(ERR_YARD_INVALID_TRANSITION, from_state=task.state, to_state=target)
    previous = task.state
    task.state = target
    return previous


async def assign(session: AsyncSession, task_id: UUID, spotter_code: str) -> MoveTask:
    task = await _get(session, task_id)
    spotter = await _one(
        session,
        select(Spotter).where(Spotter.code == spotter_code),
        entity="spotter",
        code=spotter_code,
    )
    _transition(task, "assigned")
    task.spotter_id = spotter.id
    task.assigned_at = now()
    await session.commit()
    return task


async def accept(session: AsyncSession, task_id: UUID, spotter_code: str) -> MoveTask:
    """Aceite é ato do operador. Atribuir sem aceite é fingir que alguém assumiu."""
    task = await _get(session, task_id)
    spotter = await _one(
        session,
        select(Spotter).where(Spotter.code == spotter_code),
        entity="spotter",
        code=spotter_code,
    )
    _transition(task, "accepted")
    task.spotter_id = spotter.id
    task.accepted_at = now()
    await session.commit()
    await hub.publish("yard.move.accepted", {"reference": task.reference, "spotter": spotter.code})
    return task


async def start(session: AsyncSession, task_id: UUID) -> MoveTask:
    task = await _get(session, task_id)
    _transition(task, "in_progress")
    task.started_at = now()
    await session.commit()
    return task


async def confirm(session: AsyncSession, task_id: UUID, data: ConfirmMoveIn) -> MoveTask:
    """Confirma a execução por leitura. Digitar "concluído" é exceção e exige motivo."""
    task = await _get(session, task_id)
    if data.kind == "manual" and not data.reason_code:
        raise Conflict(ERR_YARD_MOVE_CONFIRMATION_REQUIRED, reference=task.reference)

    target_slot = None
    if task.to_slot_id:
        target_slot = (
            await session.execute(select(Slot).where(Slot.id == task.to_slot_id))
        ).scalar_one_or_none()

    # QR da vaga: o código lido tem de ser o da vaga atribuída. Se não for, é desvio.
    if data.kind == "qr" and target_slot is not None and data.value != target_slot.code:
        actual = (
            await session.execute(select(Slot).where(Slot.code == data.value))
        ).scalar_one_or_none()
        session.add(
            MoveDeviation(
                detected_at=now(),
                task_id=task.id,
                vehicle_id=task.vehicle_id,
                expected_slot_id=task.to_slot_id,
                actual_slot_id=actual.id if actual else None,
                state="open",
            )
        )
        await session.commit()
        raise Conflict(
            ERR_YARD_MOVE_WRONG_SLOT, expected=target_slot.code, actual=data.value
        )

    _transition(task, "confirmed")
    task.confirmation_kind = data.kind
    task.confirmation_value = data.value
    task.reason_code = data.reason_code
    task.confirmed_at = now()

    # A posição do veículo muda de verdade: encerra a ocupação antiga e abre a nova.
    visit = await _one(session, select(Visit).where(Visit.id == task.visit_id), entity="visit")
    if target_slot is not None:
        current = (
            await session.execute(
                select(SlotOccupancy).where(
                    SlotOccupancy.visit_id == visit.id, SlotOccupancy.ended_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if current is not None:
            current.ended_at = now()
        session.add(
            SlotOccupancy(
                slot_id=target_slot.id,
                visit_id=visit.id,
                vehicle_id=visit.vehicle_id,
                started_at=now(),
            )
        )
        visit.current_slot_id = target_slot.id

    await session.commit()
    await hub.publish(
        "yard.move.confirmed", {"reference": task.reference, "kind": data.kind}
    )
    return task


async def cancel(session: AsyncSession, task_id: UUID, reason_code: str, actor: str) -> MoveTask:
    """Cancela a tarefa. Pátio muda: a manobra de dez minutos atrás pode não fazer
    mais sentido, e sem cancelamento o veículo fica com uma tarefa viva para sempre
    (o índice único impede criar a próxima)."""
    task = await _get(session, task_id)
    previous = _transition(task, "cancelled")
    task.cancelled_at = now()
    task.reason_code = reason_code
    await session.commit()
    await hub.publish(
        "yard.move.cancelled",
        {"reference": task.reference, "from_state": previous, "actor": actor},
    )
    return task


async def queue(session: AsyncSession, spotter_code: str | None = None) -> list[MoveTask]:
    """Fila ordenada por custo — o próximo movimento é o mais barato, não o mais antigo."""
    stmt = (
        select(MoveTask)
        .where(MoveTask.state.in_(("queued", "assigned", "accepted", "in_progress")))
        .order_by(MoveTask.cost_score, MoveTask.priority_rank, MoveTask.queued_at)
    )
    if spotter_code:
        spotter = await _one(
            session,
            select(Spotter).where(Spotter.code == spotter_code),
            entity="spotter",
            code=spotter_code,
        )
        stmt = stmt.where(
            (MoveTask.spotter_id == spotter.id) | (MoveTask.spotter_id.is_(None))
        )
    return list((await session.execute(stmt)).scalars().all())


async def sync_offline(session: AsyncSession, events: list[dict]) -> dict[str, int]:
    """Reconciliação do PWA: lote idempotente, ordem pelo `occurred_at` do dispositivo."""
    applied = skipped = 0
    for event in sorted(events, key=lambda e: e.get("occurred_at", "")):
        task_id = UUID(event["task_id"])
        task = (
            await session.execute(select(MoveTask).where(MoveTask.id == task_id))
        ).scalar_one_or_none()
        if task is None or task.state == "confirmed":
            skipped += 1
            continue
        try:
            if event["action"] == "accept":
                await accept(session, task_id, event["spotter_code"])
            elif event["action"] == "start":
                await start(session, task_id)
            elif event["action"] == "confirm":
                await confirm(
                    session,
                    task_id,
                    ConfirmMoveIn(
                        kind=event.get("kind", "qr"),
                        value=event.get("value"),
                        reason_code=event.get("reason_code"),
                    ),
                )
            applied += 1
        except Conflict:
            skipped += 1
    return {"applied": applied, "skipped": skipped}


# ----------------------------- doca -----------------------------

STAGE_ORDER = ["arrived", "docked", "started", "finished", "released"]


async def dock_stage(session: AsyncSession, visit_id: UUID, data: DockStageIn) -> DockVisit:
    """Cronometria por etapa: chegada → encosto → início → (pausa) → fim → liberação."""
    dock_visit = (
        await session.execute(
            select(DockVisit)
            .where(DockVisit.visit_id == visit_id, DockVisit.released_at.is_(None))
            .order_by(DockVisit.arrived_at.desc())
        )
    ).scalars().first()

    if data.stage == "arrived":
        dock = await _one(
            session,
            select(Dock).where(Dock.code == data.dock_code),
            entity="dock",
            code=data.dock_code,
        )
        dock_visit = DockVisit(
            dock_id=dock.id, visit_id=visit_id, state="arrived", arrived_at=now()
        )
        session.add(dock_visit)
        await session.commit()
        return dock_visit

    if dock_visit is None:
        raise NotFound(ERR_NOT_FOUND, entity="dock_visit", visit_id=str(visit_id))

    if data.stage == "pause":
        if not data.reason_code:
            raise Conflict(ERR_YARD_DOCK_STAGE_INVALID, stage="pause", missing="reason_code")
        dock_visit.state = "paused"
        dock_visit.pause_reason_code = data.reason_code
        dock_visit.paused_at = now()
    elif data.stage == "resume":
        if dock_visit.paused_at:
            dock_visit.paused_seconds += int((now() - dock_visit.paused_at).total_seconds())
        dock_visit.paused_at = None
        dock_visit.pause_reason_code = None
        dock_visit.state = "started"
    else:
        if data.stage not in STAGE_ORDER:
            raise Conflict(ERR_YARD_DOCK_STAGE_INVALID, stage=data.stage)
        current_index = STAGE_ORDER.index(
            "started" if dock_visit.state == "paused" else dock_visit.state
        )
        if STAGE_ORDER.index(data.stage) != current_index + 1:
            raise Conflict(
                ERR_YARD_DOCK_STAGE_INVALID, from_stage=dock_visit.state, to_stage=data.stage
            )
        if data.stage == "released":
            await ensure_no_open_hold(session, visit_id)
        setattr(dock_visit, f"{data.stage}_at", now())
        dock_visit.state = data.stage

    await session.commit()
    await hub.publish(
        "yard.dock.stage", {"visit_id": str(visit_id), "stage": dock_visit.state}
    )
    return dock_visit


async def report_discrepancy(
    session: AsyncSession, dock_visit_id: UUID, data: DiscrepancyIn
) -> Discrepancy:
    if not data.evidence_ref:
        raise Conflict(ERR_YARD_DISCREPANCY_NEEDS_EVIDENCE, kind=data.kind)
    discrepancy = Discrepancy(
        dock_visit_id=dock_visit_id,
        reported_at=now(),
        kind=data.kind,
        state="open",
        quantity=data.quantity,
        note=data.note,
        evidence_ref=data.evidence_ref,
        reported_by=data.reported_by,
    )
    session.add(discrepancy)
    # Divergência de qualidade abre pendência: a saída para até alguém decidir.
    session.add(
        VisitHold(
            visit_id=(
                await session.execute(
                    select(DockVisit.visit_id).where(DockVisit.id == dock_visit_id)
                )
            ).scalar_one(),
            kind="quality",
            reason_code=f"DISCREPANCY_{data.kind.upper()}",
            opened_at=now(),
            opened_by=data.reported_by,
            note=data.note,
        )
    )
    await session.commit()
    return discrepancy


async def open_hold(session: AsyncSession, visit_id: UUID, data: HoldIn) -> VisitHold:
    hold = VisitHold(
        visit_id=visit_id,
        kind=data.kind,
        reason_code=data.reason_code,
        opened_at=now(),
        opened_by=data.opened_by,
        note=data.note,
    )
    session.add(hold)
    await session.commit()
    return hold


async def release_hold(session: AsyncSession, hold_id: UUID, data: HoldReleaseIn) -> VisitHold:
    """Quem abriu não libera — segregação de função, garantida por CHECK no banco."""
    hold = await _one(
        session, select(VisitHold).where(VisitHold.id == hold_id), entity="visit_hold"
    )
    if hold.opened_by == data.released_by:
        raise Conflict(ERR_YARD_HOLD_SEGREGATION, opened_by=hold.opened_by)
    hold.released_at = now()
    hold.released_by = data.released_by
    await session.commit()
    return hold


async def ensure_no_open_hold(session: AsyncSession, visit_id: UUID) -> None:
    open_holds = (
        await session.execute(
            select(func.count())
            .select_from(VisitHold)
            .where(VisitHold.visit_id == visit_id, VisitHold.released_at.is_(None))
        )
    ).scalar_one()
    if open_holds:
        raise Conflict(ERR_YARD_EXIT_BLOCKED_BY_PENDENCY, open_holds=open_holds)


async def link_order(session: AsyncSession, visit_id: UUID, data: OrderLinkIn) -> OrderLink:
    link = OrderLink(
        visit_id=visit_id,
        kind=data.kind,
        external_id=data.external_id,
        quantity=data.quantity,
        unit=data.unit,
        created_at=now(),
    )
    session.add(link)
    await session.commit()
    return link


async def _get(session: AsyncSession, task_id: UUID) -> MoveTask:
    return await _one(
        session,
        select(MoveTask).where(MoveTask.id == task_id),
        entity="move_task",
        id=str(task_id),
    )
