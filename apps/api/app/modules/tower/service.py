"""Torre de controle e agente de IA.

O agente **propõe**; o humano **decide**; o comando físico só existe depois da decisão.
Não há caminho de código que pule essa ordem — e o banco recusa se alguém tentar.

As propostas aqui são heurísticas explícitas e auditáveis, não modelo caixa-preta: em
pátio, uma sugestão que ninguém consegue explicar é uma sugestão que ninguém aprova.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_NOT_FOUND,
    ERR_YARD_AI_PROPOSAL_EXPIRED,
    ERR_YARD_AI_PROPOSAL_NOT_APPROVED,
    ERR_YARD_DECISION_SEGREGATION,
    ERR_YARD_INVALID_TRANSITION,
    Conflict,
    NotFound,
)
from app.core.events import hub
from app.modules.moves import service as moves_service
from app.modules.moves.schemas import CreateMoveIn
from app.modules.scheduling import service as scheduling_service
from app.modules.scheduling.models import Appointment
from app.modules.scheduling.schemas import RescheduleIn
from app.modules.tower.models import AiProposal, BottleneckSignal, HumanDecision, ReleaseForecast
from app.modules.tower.schemas import ApproveIn, RejectIn
from app.modules.visits.models import Visit

# ASSUNÇÃO: proposta vale 10 minutos. Pátio muda rápido; sugestão velha é ruído com verniz.
PROPOSAL_TTL = timedelta(minutes=10)
MODEL_VERSION = "heuristic-v1"


def now() -> datetime:
    return datetime.now(timezone.utc)


async def _one(session: AsyncSession, stmt, entity: str, **params: Any):
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, **params)
    return obj


async def _reference(session: AsyncSession) -> str:
    seq = (await session.execute(text("SELECT nextval('ai_proposal_seq')"))).scalar_one()
    return f"AIP-{date.today().year}-{seq:06d}"


async def overview(session: AsyncSession) -> dict[str, Any]:
    """Painel único: fila, ocupação, atraso por doca, risco de demurrage e gargalo."""
    row = (
        await session.execute(
            text(
                """
                WITH open_visits AS (
                    SELECT v.*, ot.target_dwell_minutes
                      FROM visit v
                      JOIN operation_type ot ON ot.id = v.operation_type_id
                     WHERE v.state IN ('at_gate_in','in_yard','at_dock','at_gate_out')
                )
                SELECT
                  (SELECT count(*) FROM open_visits WHERE state = 'at_gate_in') AS gate_queue,
                  (SELECT count(*) FROM open_visits) AS in_yard,
                  (SELECT count(*) FROM open_visits
                    WHERE now() - arrived_at
                          > (target_dwell_minutes || ' minutes')::interval) AS over_dwell,
                  (SELECT count(*) FROM open_visits
                    WHERE now() - arrived_at
                          > ((target_dwell_minutes * 2) || ' minutes')::interval)
                        AS demurrage_risk,
                  (SELECT count(*) FROM dock WHERE status = 'occupied') AS docks_busy,
                  (SELECT count(*) FROM dock) AS docks_total,
                  (SELECT count(*) FROM appointment
                    WHERE state = 'confirmed' AND starts_at < now()
                      AND visit_id IS NULL) AS late_appointments,
                  (SELECT count(*) FROM move_task
                    WHERE state IN ('queued','assigned','accepted','in_progress'))
                        AS open_moves,
                  (SELECT count(*) FROM visit_hold WHERE released_at IS NULL) AS open_holds,
                  (SELECT count(*) FROM bottleneck_signal WHERE state = 'open') AS alarms,
                  (SELECT count(*) FROM ai_proposal WHERE state = 'proposed'
                     AND expires_at > now()) AS pending_proposals
                """
            )
        )
    ).mappings().one()
    return dict(row)


async def detect_bottlenecks(session: AsyncSession) -> list[BottleneckSignal]:
    """Sinais de gargalo com limiar explícito — alarme sem limiar é opinião."""
    detected: list[BottleneckSignal] = []
    data = await overview(session)

    checks = [
        ("gate", None, "gate_queue", Decimal(data["gate_queue"]), Decimal(8), "high"),
        ("yard", None, "over_dwell", Decimal(data["over_dwell"]), Decimal(5), "medium"),
        ("yard", None, "demurrage_risk", Decimal(data["demurrage_risk"]), Decimal(2), "critical"),
        ("dock", None, "late_appointments", Decimal(data["late_appointments"]), Decimal(3), "high"),
    ]
    for scope, ref, metric, value, threshold, severity in checks:
        if value <= threshold:
            continue
        existing = (
            await session.execute(
                select(BottleneckSignal).where(
                    BottleneckSignal.metric == metric,
                    BottleneckSignal.state.in_(("open", "acknowledged")),
                )
            )
        ).scalars().first()
        if existing is not None:
            continue
        signal = BottleneckSignal(
            detected_at=now(),
            scope=scope,
            scope_ref=ref,
            severity=severity,
            metric=metric,
            value=value,
            threshold=threshold,
            state="open",
        )
        session.add(signal)
        detected.append(signal)
    await session.commit()
    if detected:
        await hub.publish(
            "yard.tower.bottleneck", {"metrics": [s.metric for s in detected]}
        )
    return detected


async def propose(
    session: AsyncSession,
    kind: str,
    *,
    rationale: str,
    impact: dict[str, Any],
    payload: dict[str, Any],
    confidence: float | None = None,
) -> AiProposal:
    """Cria a proposta. Nasce SEMPRE em `proposed` — não existe atalho para 'approved'."""
    plant_id = (
        await session.execute(text("SELECT id FROM plant ORDER BY code LIMIT 1"))
    ).scalar_one()
    proposal = AiProposal(
        plant_id=plant_id,
        reference=await _reference(session),
        kind=kind,
        state="proposed",
        created_at=now(),
        expires_at=now() + PROPOSAL_TTL,
        rationale=rationale,
        impact_json=impact,
        payload_json=payload,
        confidence=Decimal(str(confidence)) if confidence is not None else None,
        model_version=MODEL_VERSION,
    )
    session.add(proposal)
    await session.commit()
    await hub.publish(
        "yard.ai.proposed", {"reference": proposal.reference, "kind": kind}
    )
    return proposal


async def generate_proposals(session: AsyncSession) -> list[AiProposal]:
    """Roda o agente: olha o pátio e sugere. Cada sugestão carrega o porquê e o impacto."""
    proposals: list[AiProposal] = []

    # 1. Dwell estourado → propor remanejo/priorização, com o veículo nomeado.
    stuck = (
        await session.execute(
            text(
                """
                SELECT v.id, v.reference, ve.plate,
                       EXTRACT(EPOCH FROM (now() - v.arrived_at))/60 AS dwell_min,
                       ot.target_dwell_minutes
                  FROM visit v
                  JOIN vehicle ve ON ve.id = v.vehicle_id
                  JOIN operation_type ot ON ot.id = v.operation_type_id
                 WHERE v.state IN ('in_yard','at_dock')
                   AND now() - v.arrived_at > (ot.target_dwell_minutes || ' minutes')::interval
                 ORDER BY dwell_min DESC
                 LIMIT 3
                """
            )
        )
    ).mappings().all()
    for row in stuck:
        proposals.append(
            await propose(
                session,
                "dwell_alert",
                rationale=(
                    f"Veículo {row['plate']} está há {int(row['dwell_min'])} min em pátio, "
                    f"contra meta de {row['target_dwell_minutes']} min."
                ),
                impact={
                    "visits_affected": 1,
                    "minutes_over_target": int(row["dwell_min"]) - row["target_dwell_minutes"],
                    "demurrage_risk": int(row["dwell_min"]) > row["target_dwell_minutes"] * 2,
                },
                payload={"visit_id": str(row["id"]), "visit_reference": row["reference"]},
                confidence=0.9,
            )
        )

    # 2. Agendamento confirmado e atrasado → propor resequenciamento da doca.
    late = (
        await session.execute(
            select(Appointment)
            .where(
                Appointment.state == "confirmed",
                Appointment.starts_at < now() - timedelta(minutes=30),
                Appointment.visit_id.is_(None),
            )
            .order_by(Appointment.starts_at)
            .limit(2)
        )
    ).scalars().all()
    for appointment in late:
        impact = await scheduling_service.compute_impact(
            session,
            appointment,
            now() + timedelta(minutes=30),
            now() + timedelta(minutes=30) + (appointment.ends_at - appointment.starts_at),
        )
        proposals.append(
            await propose(
                session,
                "dock_resequence",
                rationale=(
                    f"Agendamento {appointment.reference} não chegou na janela; "
                    f"empurrar 30 min libera a doca para quem está na fila."
                ),
                impact=impact.model_dump(),
                payload={
                    "appointment_id": str(appointment.id),
                    "new_starts_at": (now() + timedelta(minutes=30)).isoformat(),
                    "version": appointment.version,
                },
                confidence=0.75,
            )
        )
    return proposals


async def approve(session: AsyncSession, proposal_id: UUID, data: ApproveIn) -> AiProposal:
    """Aprovação humana. É aqui — e só aqui — que uma sugestão vira ação possível."""
    proposal = await _get(session, proposal_id)
    if proposal.state not in ("proposed", "under_review"):
        raise Conflict(
            ERR_YARD_INVALID_TRANSITION, from_state=proposal.state, to_state="approved"
        )
    if proposal.expires_at <= now():
        proposal.state = "expired"
        await session.commit()
        raise Conflict(ERR_YARD_AI_PROPOSAL_EXPIRED, reference=proposal.reference)
    # Segregação: quem revisou tecnicamente não é quem autoriza, quando os dois existem.
    if proposal.reviewed_by and proposal.reviewed_by == data.approved_by:
        raise Conflict(ERR_YARD_DECISION_SEGREGATION, actor=data.approved_by)

    proposal.state = "approved"
    proposal.approved_by = data.approved_by
    proposal.approved_at = now()
    session.add(
        HumanDecision(
            proposal_id=proposal.id,
            decided_at=now(),
            decided_by=data.approved_by,
            decision="approved",
            note=data.note,
        )
    )
    await session.commit()
    await hub.publish(
        "yard.ai.approved",
        {"reference": proposal.reference, "by": data.approved_by},
    )
    return proposal


async def reject(session: AsyncSession, proposal_id: UUID, data: RejectIn) -> AiProposal:
    """Rejeitar também é decisão registrada: é o que ensina o agente a não repetir."""
    proposal = await _get(session, proposal_id)
    proposal.state = "rejected"
    proposal.rejected_reason_code = data.reason_code
    session.add(
        HumanDecision(
            proposal_id=proposal.id,
            decided_at=now(),
            decided_by=data.rejected_by,
            decision="rejected",
            reason_code=data.reason_code,
            note=data.note,
        )
    )
    await session.commit()
    return proposal


async def execute(session: AsyncSession, proposal_id: UUID, actor: str) -> AiProposal:
    """Executa a proposta aprovada. Sem aprovação ou fora do prazo, nada acontece."""
    proposal = await _get(session, proposal_id)
    if proposal.state != "approved" or not proposal.approved_by:
        raise Conflict(ERR_YARD_AI_PROPOSAL_NOT_APPROVED, reference=proposal.reference)
    if proposal.expires_at <= now():
        proposal.state = "expired"
        await session.commit()
        raise Conflict(ERR_YARD_AI_PROPOSAL_EXPIRED, reference=proposal.reference)

    proposal.state = "executing"
    await session.commit()

    result = "noop"
    if proposal.kind == "dock_resequence":
        appointment_id = UUID(proposal.payload_json["appointment_id"])
        appointment = await _one(
            session,
            select(Appointment).where(Appointment.id == appointment_id),
            entity="appointment",
        )
        starts_at = datetime.fromisoformat(proposal.payload_json["new_starts_at"])
        duration = appointment.ends_at - appointment.starts_at
        await scheduling_service.reschedule(
            session,
            appointment_id,
            RescheduleIn(
                starts_at=starts_at,
                ends_at=starts_at + duration,
                reason_code="AI_RESEQUENCE",
                version=appointment.version,
                actor=f"ai:{proposal.reference}/{proposal.approved_by}",
            ),
        )
        result = f"appointment {appointment.reference} resequenced"
    elif proposal.kind == "slot_reassign":
        visit = await _one(
            session,
            select(Visit).where(Visit.id == UUID(proposal.payload_json["visit_id"])),
            entity="visit",
        )
        await moves_service.create_task(
            session,
            CreateMoveIn(
                visit_reference=visit.reference,
                to_slot_code=proposal.payload_json["to_slot_code"],
                priority_rank=100,
            ),
        )
        result = "move task queued"
    elif proposal.kind == "dwell_alert":
        result = "acknowledged by operator"

    proposal.state = "executed"
    proposal.executed_at = now()
    proposal.execution_result = result[:240]
    await session.commit()
    await hub.publish(
        "yard.ai.executed", {"reference": proposal.reference, "result": result}
    )
    return proposal


async def expire_stale(session: AsyncSession) -> int:
    """Propostas vencidas somem da tela — deixar lixo na torre é pior que não sugerir."""
    result = await session.execute(
        text(
            "UPDATE ai_proposal SET state = 'expired'"
            " WHERE state IN ('proposed','under_review') AND expires_at <= now()"
        )
    )
    await session.commit()
    return result.rowcount or 0


async def forecast_release(session: AsyncSession, visit_id: UUID) -> ReleaseForecast:
    """Previsão de liberação: média histórica do tipo de operação + etapas já cumpridas."""
    row = (
        await session.execute(
            text(
                """
                SELECT v.arrived_at, v.gate_in_at, v.dock_in_at, ot.target_dwell_minutes,
                       COALESCE((
                           SELECT avg(EXTRACT(EPOCH FROM (h.gate_out_at - h.arrived_at))/60)
                             FROM visit h
                            WHERE h.operation_type_id = v.operation_type_id
                              AND h.state = 'departed'
                              AND h.gate_out_at > now() - interval '30 days'
                       ), ot.target_dwell_minutes) AS avg_dwell_min
                  FROM visit v
                  JOIN operation_type ot ON ot.id = v.operation_type_id
                 WHERE v.id = :id
                """
            ),
            {"id": visit_id},
        )
    ).mappings().first()
    if row is None:
        raise NotFound(ERR_NOT_FOUND, entity="visit", id=str(visit_id))

    expected = float(row["avg_dwell_min"])
    elapsed = (now() - row["arrived_at"]).total_seconds() / 60
    remaining = max(5.0, expected - elapsed)
    forecast = ReleaseForecast(
        occurred_at=now(),
        visit_id=visit_id,
        predicted_release_at=now() + timedelta(minutes=remaining),
        confidence=Decimal("0.7"),
        model_version=MODEL_VERSION,
    )
    session.add(forecast)
    await session.commit()
    return forecast


async def acknowledge_bottleneck(
    session: AsyncSession, signal_id: UUID, actor: str
) -> BottleneckSignal:
    """ISA-18.2: reconhecer é ato de alguém, com hora — não é fechar o pop-up."""
    signal = await _one(
        session,
        select(BottleneckSignal).where(BottleneckSignal.id == signal_id),
        entity="bottleneck_signal",
    )
    signal.state = "acknowledged"
    signal.acknowledged_by = actor
    signal.acknowledged_at = now()
    await session.commit()
    return signal


async def _get(session: AsyncSession, proposal_id: UUID) -> AiProposal:
    return await _one(
        session,
        select(AiProposal).where(AiProposal.id == proposal_id),
        entity="ai_proposal",
        id=str(proposal_id),
    )
