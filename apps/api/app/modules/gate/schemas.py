from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IdentifyIn(BaseModel):
    gate_code: str
    method: str = Field(pattern="^(lpr|qr|rfid|badge|manual|whatsapp)$")
    value: str
    confidence: Decimal | None = None  # só faz sentido para leitura automática
    image_ref: str | None = None
    actor: str | None = None


class ScreeningOut(BaseModel):
    """Decisão da triagem. Não abre nada — decidir e comandar são atos separados."""

    decision: str  # admit | queue | reject
    reason_code: str | None = None
    plate: str | None = None
    appointment_reference: str | None = None
    dock_id: UUID | None = None
    requires_human: bool = False


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    position: int
    severity: str
    requires_photo: bool


class AnswerIn(BaseModel):
    item_id: UUID
    passed: bool
    note: str | None = None
    photo_ref: str | None = None


class ChecklistAnswerIn(BaseModel):
    answers: list[AnswerIn]
    actor: str | None = None  # preenchido pelo servidor a partir do token


class CommandIn(BaseModel):
    device_code: str
    action: str = Field(
        pattern="^(open_barrier|close_barrier|green_light|red_light|open_gate|"
        "display_message|lock_dock|unlock_dock)$"
    )
    visit_id: UUID | None = None
    origin: str = Field(default="human", pattern="^(human|system|ai|self_service)$")
    authorized_by: str | None = None
    reason_code: str | None = None
    # Interlock: comando de origem IA exige a decisão humana que o aprovou.
    approved_by: str | None = None
    ai_proposal_id: UUID | None = None


class CommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    requested_at: datetime
    action: str
    state: str
    origin: str
    plc_permissive: bool | None
    permissive_quality: str | None
    authorized_by: str | None
    approved_by: str | None
    failure_code: str | None
    acknowledged_at: datetime | None


class EscortIn(BaseModel):
    full_name: str
    document: str
    role: str = Field(default="helper", pattern="^(helper|visitor|contractor|driver)$")


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    kind: str
    protocol: str
    status: str
    last_seen_at: datetime | None
