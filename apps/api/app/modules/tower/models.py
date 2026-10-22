from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin


class AiProposal(PkMixin, Base):
    """Sugestão do agente.

    Nasce em `proposed` e **só** vira ação depois de `approved_by` preenchido por gente.
    Esse é o interlock do produto inteiro: sem ele, a torre abre cancela sozinha.
    """

    __tablename__ = "ai_proposal"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    reference: Mapped[str] = mapped_column(String(24), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), default="proposed")
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    rationale: Mapped[str] = mapped_column(String(600))
    # Proposta sem impacto calculado não vai para a tela: seria palpite com aparência de dado.
    impact_json: Mapped[dict] = mapped_column(JSONB)
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    model_version: Mapped[str | None] = mapped_column(String(48))
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None]
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None]
    rejected_reason_code: Mapped[str | None] = mapped_column(String(48))
    executed_at: Mapped[datetime | None]
    execution_result: Mapped[str | None] = mapped_column(String(240))


class HumanDecision(PkMixin, Base):
    """Decisão humana sobre a proposta: auditoria hoje, dado de treino amanhã."""

    __tablename__ = "human_decision"

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("ai_proposal.id"))
    decided_at: Mapped[datetime]
    decided_by: Mapped[str] = mapped_column(String(120))
    decision: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(48))
    note: Mapped[str | None] = mapped_column(String(400))


class ReleaseForecast(PkMixin, Base):
    __tablename__ = "release_forecast"

    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    predicted_release_at: Mapped[datetime]
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    model_version: Mapped[str | None] = mapped_column(String(48))
    actual_release_at: Mapped[datetime | None]
    error_minutes: Mapped[int | None]


class BottleneckSignal(PkMixin, Base):
    """Alarme de gargalo no padrão ISA-18.2: prioridade, reconhecimento, shelving."""

    __tablename__ = "bottleneck_signal"

    detected_at: Mapped[datetime]
    scope: Mapped[str] = mapped_column(String(24))
    scope_ref: Mapped[str | None] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    metric: Mapped[str] = mapped_column(String(48))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    threshold: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    state: Mapped[str] = mapped_column(String(16), default="open")
    acknowledged_by: Mapped[str | None] = mapped_column(String(120))
    acknowledged_at: Mapped[datetime | None]
