from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Segment = Literal[
    "general", "food", "beverage", "chemical", "steel", "automotive", "logistics", "agro"
]
AreaKind = Literal["parking", "staging", "quarantine", "scale_queue", "dock_approach", "cold_chain"]
SlotStatus = Literal["available", "blocked", "maintenance"]
DockStatus = Literal["available", "occupied", "blocked"]
DockDirection = Literal["inbound", "outbound", "both"]
GateDirection = Literal["in", "out", "both"]


# Mapa em metros: limites largos, mas finitos — coordenada 1e9 é erro de digitação.
def Coord(default=...):  # noqa: N802  (lê como tipo na declaração do campo)
    return Field(default=default, ge=-5000, le=5000)


def Size(default=...):  # noqa: N802
    return Field(default=default, gt=0, le=5000)


def _code(value: str) -> str:
    value = value.strip().upper()
    if not value or any(c.isspace() for c in value):
        raise ValueError("code")
    return value


class Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CodeModel(BaseModel):
    code: str = Field(min_length=1, max_length=32)

    _c = field_validator("code")(_code)


# ---------------- planta / pátio ----------------
class PlantIn(CodeModel):
    name: str = Field(min_length=2, max_length=120)
    timezone: str = Field(default="America/Sao_Paulo", max_length=64)
    segment: Segment = "general"
    city: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    active: bool = True


class PlantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    segment: Segment | None = None
    city: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    active: bool | None = None


class PlantOut(Read):
    id: UUID
    code: str
    name: str
    timezone: str
    segment: str
    city: str | None
    description: str | None
    active: bool
    zones: int = 0
    slots: int = 0
    docks: int = 0
    gates: int = 0
    scales: int = 0


class LayoutTemplate(BaseModel):
    """Assistente de novo pátio: gera uma geometria inicial editável depois."""

    zones: int = Field(default=2, ge=1, le=12)
    slots_per_zone: int = Field(default=12, ge=0, le=120)
    docks: int = Field(default=6, ge=0, le=60)
    gates: int = Field(default=2, ge=1, le=6)
    scales: int = Field(default=1, ge=0, le=6)
    cold_chain_zone: bool = False


class PlantCreateIn(PlantIn):
    template: LayoutTemplate | None = None


# ---------------- elementos do mapa ----------------
class Box(BaseModel):
    x: float = Coord()
    y: float = Coord()
    width: float = Size()
    height: float = Size()


class ZoneIn(CodeModel, Box):
    kind: AreaKind = "parking"
    color_token: str | None = Field(default=None, max_length=48)


class ZonePatch(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    kind: AreaKind | None = None
    x: float | None = Coord(None)
    y: float | None = Coord(None)
    width: float | None = Size(None)
    height: float | None = Size(None)
    color_token: str | None = Field(default=None, max_length=48)

    _c = field_validator("code")(lambda v: None if v is None else _code(v))


class ZoneOut(Read):
    id: UUID
    plant_id: UUID
    code: str
    kind: str
    x: float
    y: float
    width: float
    height: float
    color_token: str | None


class SlotIn(CodeModel, Box):
    zone_id: UUID
    kind: AreaKind = "parking"
    status: SlotStatus = "available"
    length_m: float = Field(default=18, gt=0, le=40)
    notes: str | None = Field(default=None, max_length=500)


class SlotPatch(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    zone_id: UUID | None = None
    kind: AreaKind | None = None
    status: SlotStatus | None = None
    length_m: float | None = Field(default=None, gt=0, le=40)
    x: float | None = Coord(None)
    y: float | None = Coord(None)
    width: float | None = Size(None)
    height: float | None = Size(None)
    notes: str | None = Field(default=None, max_length=500)

    _c = field_validator("code")(lambda v: None if v is None else _code(v))


class SlotOut(Read):
    id: UUID
    plant_id: UUID
    zone_id: UUID
    code: str
    kind: str
    status: str
    length_m: float
    x: float
    y: float
    width: float
    height: float
    notes: str | None


class SlotGridIn(BaseModel):
    """Gera vagas em grade dentro de uma zona — é assim que se desenha um pátio real."""

    prefix: str = Field(min_length=1, max_length=20)
    rows: int = Field(ge=1, le=30)
    cols: int = Field(ge=1, le=40)
    start_number: int = Field(default=1, ge=1, le=9999)
    slot_width: float = Field(default=38, gt=0, le=200)
    slot_height: float = Field(default=24, gt=0, le=200)
    gap_x: float = Field(default=7, ge=0, le=100)
    gap_y: float = Field(default=9, ge=0, le=100)
    margin: float = Field(default=16, ge=0, le=200)
    kind: AreaKind | None = None

    _p = field_validator("prefix")(_code)


class DockIn(CodeModel, Box):
    zone_id: UUID | None = None
    direction: DockDirection = "inbound"
    status: DockStatus = "available"


class DockPatch(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    zone_id: UUID | None = None
    direction: DockDirection | None = None
    status: DockStatus | None = None
    x: float | None = Coord(None)
    y: float | None = Coord(None)
    width: float | None = Size(None)
    height: float | None = Size(None)

    _c = field_validator("code")(lambda v: None if v is None else _code(v))


class DockOut(Read):
    id: UUID
    plant_id: UUID
    zone_id: UUID | None
    code: str
    direction: str
    status: str
    x: float
    y: float
    width: float
    height: float


class GateIn(CodeModel):
    direction: GateDirection = "both"
    x: float = Coord()
    y: float = Coord()
    active: bool = True


class GatePatch(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    direction: GateDirection | None = None
    x: float | None = Coord(None)
    y: float | None = Coord(None)
    active: bool | None = None

    _c = field_validator("code")(lambda v: None if v is None else _code(v))


class GateOut(Read):
    id: UUID
    plant_id: UUID
    code: str
    direction: str
    x: float
    y: float
    active: bool


class ScaleIn(CodeModel):
    capacity_kg: int = Field(default=80000, gt=0, le=300000)
    division_kg: int = Field(default=20, gt=0, le=1000)
    x: float = Coord()
    y: float = Coord()
    active: bool = True


class ScalePatch(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    capacity_kg: int | None = Field(default=None, gt=0, le=300000)
    division_kg: int | None = Field(default=None, gt=0, le=1000)
    x: float | None = Coord(None)
    y: float | None = Coord(None)
    active: bool | None = None

    _c = field_validator("code")(lambda v: None if v is None else _code(v))


class ScaleOut(Read):
    id: UUID
    plant_id: UUID
    code: str
    capacity_kg: int
    division_kg: int
    protocol: str
    x: float
    y: float
    active: bool


class LayoutOut(BaseModel):
    plant: PlantOut
    zones: list[ZoneOut]
    slots: list[SlotOut]
    docks: list[DockOut]
    gates: list[GateOut]
    scales: list[ScaleOut]
