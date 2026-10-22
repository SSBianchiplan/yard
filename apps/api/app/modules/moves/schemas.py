from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateMoveIn(BaseModel):
    visit_reference: str
    to_slot_code: str | None = None
    to_dock_code: str | None = None
    priority_rank: int = 500
    sla_minutes: int = 60
    sla_deadline: datetime | None = None
    # Idempotência do PWA offline: mesmo id, mesma tarefa.
    client_event_id: str | None = None


class ConfirmMoveIn(BaseModel):
    kind: str = Field(default="qr", pattern="^(qr|rtls|photo|manual)$")
    value: str | None = None
    reason_code: str | None = None  # obrigatório quando kind = manual


class MoveTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str
    state: str
    plate: str | None = None
    visit_id: UUID
    visit_reference: str | None = None
    from_slot_code: str | None = None
    to_slot_code: str | None = None
    to_dock_code: str | None = None
    spotter_code: str | None = None
    priority_rank: int
    cost_score: Decimal
    distance_m: Decimal | None
    sla_deadline: datetime | None
    queued_at: datetime | None
    accepted_at: datetime | None
    confirmed_at: datetime | None
    confirmation_kind: str | None


class DockStageIn(BaseModel):
    stage: str = Field(pattern="^(arrived|docked|started|pause|resume|finished|released)$")
    dock_code: str | None = None
    reason_code: str | None = None  # obrigatório na pausa


class DockVisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dock_id: UUID
    visit_id: UUID
    state: str
    arrived_at: datetime
    docked_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    released_at: datetime | None
    paused_seconds: int
    pause_reason_code: str | None


class DiscrepancyIn(BaseModel):
    kind: str = Field(
        pattern="^(damage|shortage|overage|temperature|humidity|seal_broken|other)$"
    )
    evidence_ref: str  # foto obrigatória — o CHECK do banco também exige
    quantity: Decimal | None = None
    note: str | None = None
    reported_by: str | None = None  # preenchido pelo servidor a partir do token


class HoldIn(BaseModel):
    kind: str = Field(pattern="^(quality|fiscal|safety|commercial)$")
    reason_code: str
    opened_by: str | None = None  # preenchido pelo servidor a partir do token
    note: str | None = None


class HoldReleaseIn(BaseModel):
    released_by: str | None = None  # preenchido pelo servidor a partir do token


class HoldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    reason_code: str
    opened_at: datetime
    opened_by: str
    released_at: datetime | None
    released_by: str | None


class OrderLinkIn(BaseModel):
    kind: str = Field(
        pattern="^(production_order|purchase_order|sales_order|packing_list|transfer)$"
    )
    external_id: str
    quantity: Decimal | None = None
    unit: str | None = None
