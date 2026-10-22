from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Computed, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class Spotter(PkMixin, TimestampMixin, Base):
    __tablename__ = "spotter"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    full_name: Mapped[str] = mapped_column(String(160))
    shift_code: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MoveTask(PkMixin, TimestampMixin, Base):
    """Tarefa de manobra. Aceite é ato do operador; confirmação é leitura, não botão."""

    __tablename__ = "move_task"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    reference: Mapped[str] = mapped_column(String(24), unique=True)
    state: Mapped[str] = mapped_column(String(16), default="proposed")
    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle.id"))
    from_slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot.id"))
    to_slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot.id"))
    from_dock_id: Mapped[UUID | None] = mapped_column(ForeignKey("dock.id"))
    to_dock_id: Mapped[UUID | None] = mapped_column(ForeignKey("dock.id"))
    spotter_id: Mapped[UUID | None] = mapped_column(ForeignKey("spotter.id"))

    priority_rank: Mapped[int] = mapped_column(default=500)
    cost_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    sla_deadline: Mapped[datetime | None]

    queued_at: Mapped[datetime | None]
    assigned_at: Mapped[datetime | None]
    accepted_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    confirmed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]

    confirmation_kind: Mapped[str | None] = mapped_column(String(16))
    confirmation_value: Mapped[str | None] = mapped_column(String(120))
    reason_code: Mapped[str | None] = mapped_column(String(48))
    # Idempotência do PWA offline: o mesmo evento reenviado não cria tarefa nova.
    client_event_id: Mapped[str | None] = mapped_column(String(64))


class MoveDeviation(PkMixin, Base):
    """Ativo parado em vaga diferente da atribuída. Gera tarefa corretiva, não só alerta."""

    __tablename__ = "move_deviation"

    detected_at: Mapped[datetime]
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("move_task.id"))
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle.id"))
    expected_slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot.id"))
    actual_slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot.id"))
    state: Mapped[str] = mapped_column(String(16), default="open")
    corrective_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("move_task.id"))


class DockVisit(PkMixin, TimestampMixin, Base):
    """Ocupação de doca com cronometria por etapa — é daqui que sai a análise de gargalo."""

    __tablename__ = "dock_visit"

    dock_id: Mapped[UUID] = mapped_column(ForeignKey("dock.id"))
    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    appointment_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointment.id"))
    state: Mapped[str] = mapped_column(String(16), default="arrived")
    arrived_at: Mapped[datetime]
    docked_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    released_at: Mapped[datetime | None]
    paused_seconds: Mapped[int] = mapped_column(default=0)
    pause_reason_code: Mapped[str | None] = mapped_column(String(48))
    paused_at: Mapped[datetime | None]
    period: Mapped[object] = mapped_column(
        TSTZRANGE, Computed("tstzrange(arrived_at, released_at)", persisted=True)
    )


class OrderLink(PkMixin, Base):
    """Vínculo com OP, OC, pedido ou romaneio. Operação sem vínculo é exceção."""

    __tablename__ = "order_link"

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    kind: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime]


class Discrepancy(PkMixin, Base):
    """Avaria, falta, sobra, temperatura, lacre. Sem foto não entra — CHECK no banco."""

    __tablename__ = "discrepancy"

    dock_visit_id: Mapped[UUID] = mapped_column(ForeignKey("dock_visit.id"))
    reported_at: Mapped[datetime]
    kind: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(16), default="open")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    note: Mapped[str | None] = mapped_column(String(400))
    evidence_ref: Mapped[str] = mapped_column(String(240))
    reported_by: Mapped[str] = mapped_column(String(120))
    reviewed_by: Mapped[str | None] = mapped_column(String(120))


class VisitHold(PkMixin, Base):
    """Pendência de qualidade, fiscal, segurança ou comercial. Quem abre não libera."""

    __tablename__ = "visit_hold"

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    kind: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(48))
    opened_at: Mapped[datetime]
    opened_by: Mapped[str] = mapped_column(String(120))
    released_at: Mapped[datetime | None]
    released_by: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(400))
