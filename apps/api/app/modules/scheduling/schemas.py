from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AppointmentIn(BaseModel):
    dock_code: str
    plate: str
    operation_type_code: str
    starts_at: datetime
    ends_at: datetime
    driver_document: str | None = None
    product_sku: str | None = None
    resource_code: str | None = None
    channel: str = "internal"
    actor: str | None = None


class RescheduleIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    dock_code: str | None = None
    # Reprogramação sem motivo não existe — a regra está no CHECK e aqui.
    reason_code: str = Field(min_length=2, max_length=48)
    version: int
    actor: str | None = None


class CancelIn(BaseModel):
    reason_code: str = Field(min_length=2, max_length=48)
    version: int
    actor: str | None = None


class ConfirmIn(BaseModel):
    version: int
    slot_code: str | None = None  # vazio = reserva automática
    actor: str | None = None


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str
    state: str
    version: int
    dock_code: str
    plate: str
    carrier_name: str | None = None
    product_name: str | None = None
    operation_type_code: str
    resource_code: str | None = None
    slot_code: str | None = None
    starts_at: datetime
    ends_at: datetime
    priority_code: str | None = None
    priority_rank: int
    channel: str
    visit_id: UUID | None = None


class AvailabilityWindow(BaseModel):
    dock_code: str
    starts_at: datetime
    ends_at: datetime
    available: bool
    reason_code: str | None = None
    resource_remaining: int | None = None


class ImpactOut(BaseModel):
    """Impacto de mover este agendamento: o programador decide vendo o custo."""

    displaced_appointments: int
    delayed_minutes: int
    conflicting_references: list[str]


class ChangeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurred_at: datetime
    actor: str | None
    reason_code: str | None
    from_state: str | None
    to_state: str | None
    from_starts_at: datetime | None
    to_starts_at: datetime | None
    impact_json: dict
