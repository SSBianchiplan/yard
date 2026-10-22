from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class Signal(PkMixin, TimestampMixin, Base):
    """Tag normalizada no modelo de informação único.

    `path` é o endereço que a aplicação conhece (plant/area/device/signal);
    `source_address` é o endereço cru do CLP — e fica escondido aqui, de propósito.
    """

    __tablename__ = "signal"

    device_id: Mapped[UUID] = mapped_column(ForeignKey("device.id"))
    code: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(24))
    data_type: Mapped[str] = mapped_column(String(16), default="bool")
    unit: Mapped[str | None] = mapped_column(String(16))
    safety_related: Mapped[bool] = mapped_column(Boolean, default=False)
    # Acima disso a leitura é obsoleta, e obsoleto não decide nada.
    stale_after_seconds: Mapped[int] = mapped_column(default=30)
    source_address: Mapped[str | None] = mapped_column(String(160))


class SignalReading(PkMixin, Base):
    """Leitura de campo.

    `occurred_at` é a hora do campo; `received_at`, a do servidor. Com rede caindo, os
    dois divergem — e a ordem que vale para reconstruir a história é a do campo.
    """

    __tablename__ = "signal_reading"

    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    received_at: Mapped[datetime]
    signal_id: Mapped[UUID] = mapped_column(ForeignKey("signal.id"))
    device_id: Mapped[UUID] = mapped_column(ForeignKey("device.id"))
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    value_text: Mapped[str | None] = mapped_column(String(240))
    quality: Mapped[str] = mapped_column(String(16), default="good")
    sequence_number: Mapped[int | None]
    batch_id: Mapped[UUID | None]


class DeviceHealth(PkMixin, Base):
    __tablename__ = "device_health"

    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("device.id"))
    status: Mapped[str] = mapped_column(String(16))
    latency_ms: Mapped[int | None]
    error_code: Mapped[str | None] = mapped_column(String(48))
    detail: Mapped[str | None] = mapped_column(String(240))


class EdgeBatch(PkMixin, Base):
    """Lote vindo do buffer local. Reenviar o mesmo lote não duplica nada."""

    __tablename__ = "edge_batch"

    batch_key: Mapped[str] = mapped_column(String(80), unique=True)
    edge_node: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime]
    event_count: Mapped[int] = mapped_column(default=0)
    applied_count: Mapped[int] = mapped_column(default=0)
    skipped_count: Mapped[int] = mapped_column(default=0)
    oldest_event_at: Mapped[datetime | None]
    newest_event_at: Mapped[datetime | None]


class RtlsPosition(PkMixin, Base):
    """Posição por RTLS — camada opcional. O sistema funciona sem; com ela, acerta mais."""

    __tablename__ = "rtls_position"

    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    vehicle_id: Mapped[UUID | None] = mapped_column(ForeignKey("vehicle.id"))
    asset_tag: Mapped[str | None] = mapped_column(String(64))
    technology: Mapped[str] = mapped_column(String(16))
    x: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    y: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot.id"))
    quality: Mapped[str] = mapped_column(String(16), default="good")
