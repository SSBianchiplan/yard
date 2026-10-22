from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class ScaleReading(PkMixin, Base):
    """Telemetria do indicador. Hypertable: chega muita coisa e envelhece rápido."""

    __tablename__ = "scale_reading"

    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    scale_id: Mapped[UUID] = mapped_column(ForeignKey("scale.id"))
    weight_kg: Mapped[int]
    stable: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[str] = mapped_column(String(16), default="good")
    vehicle_positioned: Mapped[bool | None] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(24), default="device")


class WeighingTicket(PkMixin, TimestampMixin, Base):
    """Ticket de pesagem. Fechado, é imutável: correção é ticket novo com rastro."""

    __tablename__ = "weighing_ticket"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    reference: Mapped[str] = mapped_column(String(24), unique=True)
    state: Mapped[str] = mapped_column(String(16), default="open")
    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle.id"))
    scale_id: Mapped[UUID] = mapped_column(ForeignKey("scale.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("product.id"))
    mode: Mapped[str] = mapped_column(String(16), default="double")

    gross_kg: Mapped[int | None]
    tare_kg: Mapped[int | None]
    net_kg: Mapped[int | None]
    tare_source: Mapped[str | None] = mapped_column(String(16))
    gross_at: Mapped[datetime | None]
    tare_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]

    document_number: Mapped[str | None] = mapped_column(String(64))
    document_net_kg: Mapped[int | None]
    divergence_kg: Mapped[int | None]
    divergence_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    tolerance_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=Decimal("0.5"))

    source: Mapped[str] = mapped_column(String(16), default="device")
    reason_code: Mapped[str | None] = mapped_column(String(48))
    operator: Mapped[str | None] = mapped_column(String(120))
    second_factor_user: Mapped[str | None] = mapped_column(String(120))
    image_ref: Mapped[str | None] = mapped_column(String(240))
    integrity_hash: Mapped[str | None] = mapped_column(String(64))
    reprint_count: Mapped[int] = mapped_column(default=0)


class WeighingCapture(PkMixin, Base):
    """Cada captura de peso, com imagem do instante — antifraude começa aqui."""

    __tablename__ = "weighing_capture"

    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("weighing_ticket.id"))
    occurred_at: Mapped[datetime]
    kind: Mapped[str] = mapped_column(String(16))
    weight_kg: Mapped[int]
    stable: Mapped[bool] = mapped_column(Boolean)
    vehicle_positioned: Mapped[bool] = mapped_column(Boolean)
    image_ref: Mapped[str | None] = mapped_column(String(240))
    operator: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(16), default="device")


class AxleWeight(PkMixin, Base):
    __tablename__ = "axle_weight"

    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("weighing_ticket.id"))
    axle_number: Mapped[int]
    weight_kg: Mapped[int]


class WeighingReprint(PkMixin, Base):
    """Reimpressão é auditada: quem, quando, por quê."""

    __tablename__ = "weighing_reprint"

    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("weighing_ticket.id"))
    occurred_at: Mapped[datetime]
    actor: Mapped[str] = mapped_column(String(120))
    reason_code: Mapped[str] = mapped_column(String(48))


class TareRecord(PkMixin, Base):
    """Tara aferida. Diverge da cadastral acima do limite? O ticket marca e alguém decide."""

    __tablename__ = "tare_record"

    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle.id"))
    measured_at: Mapped[datetime]
    tare_kg: Mapped[int]
    scale_id: Mapped[UUID | None] = mapped_column(ForeignKey("scale.id"))
    ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("weighing_ticket.id"))
