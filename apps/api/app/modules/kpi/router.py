"""KPIs da Fatia 1. O resto do painel (demurrage, aderência) chega com as Fatias 2 e 7."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires

router = APIRouter(
    prefix="/kpi",
    tags=["kpi"],
    dependencies=[Depends(requires(Role.CONTROLLER, Role.SUPERVISOR))],
)


class YardOverview(BaseModel):
    vehicles_in_yard: int
    at_gate_in: int
    at_dock: int
    slots_total: int
    slots_occupied: int
    slot_occupancy_pct: float
    docks_total: int
    docks_occupied: int
    dock_occupancy_pct: float
    gate_in_today: int
    gate_out_today: int
    avg_dwell_seconds: int
    p95_dwell_seconds: int
    over_target_dwell: int
    manual_event_pct: float


QUERY = text(
    """
    WITH open_visits AS (
        SELECT v.*, ot.target_dwell_minutes
        FROM visit v JOIN operation_type ot ON ot.id = v.operation_type_id
        WHERE v.state IN ('at_gate_in','in_yard','at_dock','at_gate_out')
    ),
    closed_today AS (
        SELECT EXTRACT(EPOCH FROM (gate_out_at - arrived_at)) AS dwell
        FROM visit WHERE state = 'departed' AND gate_out_at >= date_trunc('day', now())
    )
    SELECT
      (SELECT count(*) FROM open_visits WHERE state IN ('in_yard','at_dock','at_gate_out'))
        AS vehicles_in_yard,
      (SELECT count(*) FROM open_visits WHERE state = 'at_gate_in') AS at_gate_in,
      (SELECT count(*) FROM open_visits WHERE state = 'at_dock') AS at_dock,
      (SELECT count(*) FROM slot) AS slots_total,
      (SELECT count(*) FROM slot_occupancy WHERE ended_at IS NULL) AS slots_occupied,
      (SELECT count(*) FROM dock) AS docks_total,
      (SELECT count(*) FROM dock WHERE status = 'occupied') AS docks_occupied,
      (SELECT count(*) FROM visit WHERE gate_in_at >= date_trunc('day', now())) AS gate_in_today,
      (SELECT count(*) FROM visit WHERE gate_out_at >= date_trunc('day', now())) AS gate_out_today,
      COALESCE((SELECT avg(dwell) FROM closed_today), 0) AS avg_dwell,
      COALESCE((SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY dwell) FROM closed_today), 0)
        AS p95_dwell,
      (SELECT count(*) FROM open_visits
        WHERE now() - arrived_at > (target_dwell_minutes || ' minutes')::interval)
        AS over_target,
      COALESCE((SELECT 100.0 * count(*) FILTER (WHERE source = 'manual') / NULLIF(count(*),0)
                FROM visit_event WHERE occurred_at >= now() - interval '24 hours'), 0)
        AS manual_pct
    """
)


@router.get("/yard-overview", response_model=YardOverview)
async def yard_overview(session: AsyncSession = Depends(get_session)) -> YardOverview:
    row = (await session.execute(QUERY)).mappings().one()
    slots_total = row["slots_total"] or 0
    docks_total = row["docks_total"] or 0
    return YardOverview(
        vehicles_in_yard=row["vehicles_in_yard"],
        at_gate_in=row["at_gate_in"],
        at_dock=row["at_dock"],
        slots_total=slots_total,
        slots_occupied=row["slots_occupied"],
        slot_occupancy_pct=round(100 * row["slots_occupied"] / slots_total, 1) if slots_total else 0,
        docks_total=docks_total,
        docks_occupied=row["docks_occupied"],
        dock_occupancy_pct=round(100 * row["docks_occupied"] / docks_total, 1) if docks_total else 0,
        gate_in_today=row["gate_in_today"],
        gate_out_today=row["gate_out_today"],
        avg_dwell_seconds=int(row["avg_dwell"]),
        p95_dwell_seconds=int(row["p95_dwell"]),
        over_target_dwell=row["over_target"],
        manual_event_pct=round(float(row["manual_pct"]), 1),
    )
