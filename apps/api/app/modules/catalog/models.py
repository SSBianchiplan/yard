from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class Plant(PkMixin, TimestampMixin, Base):
    __tablename__ = "plant"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    # Segmento é código (general, food, …): o rótulo é traduzido pela UI.
    segment: Mapped[str] = mapped_column(String(32), default="general")
    city: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Carrier(PkMixin, TimestampMixin, Base):
    __tablename__ = "carrier"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    tax_id: Mapped[str | None] = mapped_column(String(32))  # CNPJ — termo próprio, não traduz
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Driver(PkMixin, TimestampMixin, Base):
    __tablename__ = "driver"

    full_name: Mapped[str] = mapped_column(String(160))
    document: Mapped[str] = mapped_column(String(32), unique=True)  # CPF
    license_number: Mapped[str | None] = mapped_column(String(32))  # CNH
    license_expires_on: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(32))
    carrier_id: Mapped[UUID | None] = mapped_column(ForeignKey("carrier.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # LGPD: document/phone são dado pessoal. Retenção e anonimização na Fatia transversal.


class Vehicle(PkMixin, TimestampMixin, Base):
    __tablename__ = "vehicle"

    plate: Mapped[str] = mapped_column(String(16), unique=True)
    trailer_plate: Mapped[str | None] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(32))  # VehicleKind
    carrier_id: Mapped[UUID | None] = mapped_column(ForeignKey("carrier.id"))
    axles: Mapped[int | None]
    tare_kg: Mapped[int | None]  # tara cadastral
    tare_source: Mapped[str] = mapped_column(String(16), default="registered")
    max_gross_kg: Mapped[int | None]
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(PkMixin, TimestampMixin, Base):
    __tablename__ = "product"

    sku: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    hazardous: Mapped[bool] = mapped_column(Boolean, default=False)
    unit: Mapped[str] = mapped_column(String(8), default="kg")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OperationType(PkMixin, TimestampMixin, Base):
    __tablename__ = "operation_type"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    direction: Mapped[str] = mapped_column(String(16))  # OperationDirection
    requires_weighing: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_dock: Mapped[bool] = mapped_column(Boolean, default=True)
    target_dwell_minutes: Mapped[int] = mapped_column(default=90)
    notes: Mapped[str | None] = mapped_column(Text)
    # O nome exibido é traduzido pela UI a partir de `code`. Não guarde rótulo humano aqui.
