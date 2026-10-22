from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class Visit(PkMixin, TimestampMixin, Base):
    """Uma passagem de veículo pelo pátio: gate-in → pátio → doca → gate-out.

    É o agregado central. Agendamento (Fatia 2), pesagem (3) e tarefas (5) penduram aqui.
    """

    __tablename__ = "visit"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    reference: Mapped[str] = mapped_column(String(24), unique=True)  # YRD-2026-000123
    state: Mapped[str] = mapped_column(String(24), default="at_gate_in")

    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle.id"))
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("driver.id"))
    carrier_id: Mapped[UUID | None] = mapped_column(ForeignKey("carrier.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("product.id"))
    operation_type_id: Mapped[UUID] = mapped_column(ForeignKey("operation_type.id"))
    appointment_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointment.id"))

    gate_in_id: Mapped[UUID | None] = mapped_column(ForeignKey("gate.id"))
    gate_out_id: Mapped[UUID | None] = mapped_column(ForeignKey("gate.id"))
    current_slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot.id"))
    current_dock_id: Mapped[UUID | None] = mapped_column(ForeignKey("dock.id"))

    arrived_at: Mapped[datetime]              # chegou à guarita
    gate_in_at: Mapped[datetime | None]       # liberado para o pátio
    dock_in_at: Mapped[datetime | None]
    dock_out_at: Mapped[datetime | None]
    gate_out_at: Mapped[datetime | None]

    seal_number: Mapped[str | None] = mapped_column(String(48))  # lacre
    document_number: Mapped[str | None] = mapped_column(String(64))  # NF-e / CT-e
    notes: Mapped[str | None] = mapped_column(Text)
    blocked_reason_code: Mapped[str | None] = mapped_column(String(48))  # código, não texto


class VisitEvent(PkMixin, Base):
    """Trilha append-only. UPDATE/DELETE bloqueados por trigger (migration 0001).

    Hypertable Timescale quando a extensão existe; tabela comum quando não.
    """

    __tablename__ = "visit_event"

    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    event_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(24), default="manual")
    actor: Mapped[str | None] = mapped_column(String(120))
    from_state: Mapped[str | None] = mapped_column(String(24))
    to_state: Mapped[str | None] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
