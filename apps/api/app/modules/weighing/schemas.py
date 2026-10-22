from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OpenTicketIn(BaseModel):
    visit_reference: str
    scale_code: str
    mode: str = "double"  # double | fixed_tare | axle
    document_number: str | None = None
    document_net_kg: int | None = None
    tolerance_pct: float = 0.5
    operator: str | None = None
    reentry_justified: bool = False


class CaptureIn(BaseModel):
    kind: str = Field(pattern="^(gross|tare|axle)$")
    # Laço indutivo / fotocélula. Na Fatia 6 vira sinal de campo; aqui a guarita confirma.
    vehicle_positioned: bool = True
    image_ref: str | None = None
    operator: str | None = None
    axle_number: int | None = None
    # Caminho de exceção: peso digitado exige motivo + segundo fator.
    manual_weight_kg: int | None = None
    reason_code: str | None = None
    second_factor_user: str | None = None


class CloseTicketIn(BaseModel):
    image_ref: str | None = None
    document_number: str | None = None
    document_net_kg: int | None = None


class ReprintIn(BaseModel):
    actor: str
    reason_code: str


class CaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurred_at: datetime
    kind: str
    weight_kg: int
    stable: bool
    vehicle_positioned: bool
    source: str
    image_ref: str | None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str
    state: str
    visit_reference: str | None = None
    plate: str | None = None
    scale_code: str | None = None
    mode: str
    gross_kg: int | None
    tare_kg: int | None
    net_kg: int | None
    tare_source: str | None
    document_number: str | None
    document_net_kg: int | None
    divergence_kg: int | None
    divergence_pct: Decimal | None
    tolerance_pct: Decimal
    within_tolerance: bool | None = None
    tare_drift_pct: Decimal | None = None
    source: str
    operator: str | None
    integrity_hash: str | None
    reprint_count: int
    closed_at: datetime | None
    captures: list[CaptureOut] = []


class LiveReadingOut(BaseModel):
    scale_code: str
    weight_kg: int
    stable: bool
    quality: str
    occurred_at: datetime
