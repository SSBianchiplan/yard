from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReadingIn(BaseModel):
    """Leitura de campo. `occurred_at` é a hora do CAMPO — com rede caída, é a que vale."""

    path: str
    occurred_at: datetime
    value_bool: bool | None = None
    value_num: Decimal | None = None
    value_text: str | None = None
    quality: str = Field(default="good", pattern="^(good|stale|invalid|no_comm)$")
    sequence_number: int | None = None


class EdgeBatchIn(BaseModel):
    """Lote do buffer local. Mesma chave = mesmo lote; reenviar é seguro."""

    batch_key: str
    edge_node: str
    readings: list[ReadingIn]


class SignalIn(BaseModel):
    device_code: str
    code: str
    path: str
    kind: str = Field(pattern="^(permissive|status|measure|command_feedback|alarm|position)$")
    data_type: str = Field(default="bool", pattern="^(bool|int|float|string)$")
    unit: str | None = None
    safety_related: bool = False
    stale_after_seconds: int = 30
    source_address: str | None = None


class DeviceHealthIn(BaseModel):
    status: str = Field(pattern="^(online|degraded|offline|maintenance)$")
    latency_ms: int | None = None
    error_code: str | None = None


class DeviceAvailabilityOut(BaseModel):
    code: str
    kind: str
    status: str
    last_seen_at: datetime | None
    availability_pct: Decimal
    incidents: int


class RtlsIn(BaseModel):
    technology: str = Field(pattern="^(gps|rtk|uwb|ble|rfid)$")
    x: Decimal
    y: Decimal
    vehicle_id: UUID | None = None
    asset_tag: str | None = None
    accuracy_m: Decimal | None = None
    slot_code: str | None = None
    quality: str = Field(default="good", pattern="^(good|stale|invalid|no_comm)$")
    occurred_at: datetime | None = None


class RtlsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurred_at: datetime
    technology: str
    x: Decimal
    y: Decimal
    accuracy_m: Decimal | None
    slot_id: UUID | None
    quality: str
