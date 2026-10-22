from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, Computed, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class Zone(PkMixin, TimestampMixin, Base):
    __tablename__ = "zone"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(32), default="parking")
    # Geometria do mapa em coordenadas de pátio (metros), renderizada em SVG pelo YardMap.
    x: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    y: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    width: Mapped[float] = mapped_column(Numeric(10, 2), default=100)
    height: Mapped[float] = mapped_column(Numeric(10, 2), default=100)
    color_token: Mapped[str | None] = mapped_column(String(48))


class Gate(PkMixin, TimestampMixin, Base):
    __tablename__ = "gate"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    direction: Mapped[str] = mapped_column(String(16), default="both")  # in | out | both
    x: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    y: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Scale(PkMixin, TimestampMixin, Base):
    """Balança rodoviária: cadastro + como falar com o indicador."""

    __tablename__ = "scale"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    capacity_kg: Mapped[int] = mapped_column(default=80000)
    x: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    y: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Fatia 3: qual driver falar e como decidir que o peso assentou.
    protocol: Mapped[str] = mapped_column(String(24), default="simulator")
    endpoint: Mapped[str | None] = mapped_column(String(120))
    division_kg: Mapped[int] = mapped_column(default=20)
    stability_window_seconds: Mapped[int] = mapped_column(default=3)
    stability_tolerance_kg: Mapped[int] = mapped_column(default=20)
    status: Mapped[str] = mapped_column(String(16), default="online")


class Dock(PkMixin, TimestampMixin, Base):
    __tablename__ = "dock"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    zone_id: Mapped[UUID | None] = mapped_column(ForeignKey("zone.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    direction: Mapped[str] = mapped_column(String(16), default="inbound")
    status: Mapped[str] = mapped_column(String(16), default="available")
    x: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    y: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    width: Mapped[float] = mapped_column(Numeric(10, 2), default=8)
    height: Mapped[float] = mapped_column(Numeric(10, 2), default=14)


class Slot(PkMixin, TimestampMixin, Base):
    """Vaga de pátio."""

    __tablename__ = "slot"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    zone_id: Mapped[UUID] = mapped_column(ForeignKey("zone.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(32), default="parking")
    status: Mapped[str] = mapped_column(String(16), default="available")
    length_m: Mapped[float] = mapped_column(Numeric(6, 2), default=18)
    x: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    y: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    width: Mapped[float] = mapped_column(Numeric(10, 2), default=4)
    height: Mapped[float] = mapped_column(Numeric(10, 2), default=12)
    notes: Mapped[str | None] = mapped_column(Text)


class SlotOccupancy(PkMixin, TimestampMixin, Base):
    """Ocupação temporal de vaga.

    Os dois invariantes caros na app e baratos no banco vivem aqui, como EXCLUDE:
      - uma vaga não tem duas ocupações sobrepostas;
      - um veículo não ocupa duas vagas ao mesmo tempo.
    `period` é coluna gerada a partir de started_at/ended_at (ver migration 0001).
    """

    __tablename__ = "slot_occupancy"

    slot_id: Mapped[UUID] = mapped_column(ForeignKey("slot.id"))
    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle.id"))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    period: Mapped[object] = mapped_column(
        TSTZRANGE,
        Computed("tstzrange(started_at, ended_at)", persisted=True),
    )
