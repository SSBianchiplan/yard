from datetime import datetime, time
from uuid import UUID

from sqlalchemy import Boolean, Computed, ForeignKey, String, Time
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class Resource(PkMixin, TimestampMixin, Base):
    """Recurso de descarga: empilhadeira, moega, equipe. Capacidade é finita — o ponto todo."""

    __tablename__ = "resource"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    capacity: Mapped[int] = mapped_column(default=1)


class ShiftCalendar(PkMixin, TimestampMixin, Base):
    __tablename__ = "shift_calendar"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    weekday: Mapped[int]
    starts_time: Mapped[time] = mapped_column(Time)
    ends_time: Mapped[time] = mapped_column(Time)


class PlantStoppage(PkMixin, TimestampMixin, Base):
    __tablename__ = "plant_stoppage"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    reason_code: Mapped[str] = mapped_column(String(48))
    period: Mapped[object] = mapped_column(TSTZRANGE)


class PriorityRule(PkMixin, TimestampMixin, Base):
    """Prioridade é dado, não `if` no código: ordem por `rank`, casamento por `match_json`."""

    __tablename__ = "priority_rule"

    code: Mapped[str] = mapped_column(String(48), unique=True)
    rank: Mapped[int]
    match_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Appointment(PkMixin, TimestampMixin, Base):
    __tablename__ = "appointment"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    reference: Mapped[str] = mapped_column(String(24), unique=True)
    state: Mapped[str] = mapped_column(String(16), default="requested")

    dock_id: Mapped[UUID] = mapped_column(ForeignKey("dock.id"))
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle.id"))
    driver_id: Mapped[UUID | None] = mapped_column(ForeignKey("driver.id"))
    carrier_id: Mapped[UUID | None] = mapped_column(ForeignKey("carrier.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("product.id"))
    operation_type_id: Mapped[UUID] = mapped_column(ForeignKey("operation_type.id"))
    resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resource.id"))
    visit_id: Mapped[UUID | None] = mapped_column(ForeignKey("visit.id"))
    slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot.id"))

    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    priority_code: Mapped[str | None] = mapped_column(String(48))
    priority_rank: Mapped[int] = mapped_column(default=999)
    created_by: Mapped[str | None] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(16), default="internal")
    # Concorrência otimista: dois programadores no mesmo calendário não se sobrescrevem
    # em silêncio — o segundo recebe ERR_YARD_APPOINTMENT_STALE com o estado atual.
    version: Mapped[int] = mapped_column(default=1)


class AppointmentChangeLog(PkMixin, Base):
    """Rastro de reprogramação: quem, quando, por quê e qual o impacto na fila."""

    __tablename__ = "appointment_change_log"

    appointment_id: Mapped[UUID] = mapped_column(ForeignKey("appointment.id"))
    occurred_at: Mapped[datetime]
    actor: Mapped[str | None] = mapped_column(String(120))
    reason_code: Mapped[str | None] = mapped_column(String(48))
    from_state: Mapped[str | None] = mapped_column(String(16))
    to_state: Mapped[str | None] = mapped_column(String(16))
    from_starts_at: Mapped[datetime | None]
    to_starts_at: Mapped[datetime | None]
    impact_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class SlotReservation(PkMixin, TimestampMixin, Base):
    """Reserva nasce na confirmação do agendamento e morre no gate-out ou por timeout."""

    __tablename__ = "slot_reservation"

    slot_id: Mapped[UUID] = mapped_column(ForeignKey("slot.id"))
    appointment_id: Mapped[UUID] = mapped_column(ForeignKey("appointment.id"))
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle.id"))
    state: Mapped[str] = mapped_column(String(16), default="active")
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    period: Mapped[object] = mapped_column(
        TSTZRANGE, Computed("tstzrange(starts_at, ends_at)", persisted=True)
    )
