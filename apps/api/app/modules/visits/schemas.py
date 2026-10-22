from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EventSource, VisitState


class GateInIn(BaseModel):
    plate: str = Field(min_length=4, max_length=16)
    driver_document: str = Field(min_length=4, max_length=32)
    operation_type_code: str
    product_sku: str | None = None
    gate_code: str | None = None
    appointment_reference: str | None = None  # QR do agendamento (leitura chega na Fatia 4)
    document_number: str | None = None
    seal_number: str | None = None
    notes: str | None = None
    source: EventSource = EventSource.MANUAL
    actor: str | None = None


class SlotAssignIn(BaseModel):
    slot_code: str | None = None  # vazio = alocação automática
    actor: str | None = None
    source: EventSource = EventSource.MANUAL


class DockAssignIn(BaseModel):
    dock_code: str
    actor: str | None = None
    source: EventSource = EventSource.MANUAL


class RejectVisitIn(BaseModel):
    """Recusa na triagem: motivo é obrigatório — "não entrou" sem porquê não audita."""

    reason_code: str = Field(min_length=2, max_length=48)
    note: str | None = None
    actor: str | None = None
    source: EventSource = EventSource.MANUAL


class GateOutIn(BaseModel):
    gate_code: str | None = None
    actor: str | None = None
    source: EventSource = EventSource.MANUAL


class VisitEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurred_at: datetime
    event_type: str
    source: str
    actor: str | None
    from_state: str | None
    to_state: str | None
    payload: dict


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str
    state: VisitState
    plate: str
    trailer_plate: str | None = None
    driver_name: str
    carrier_name: str | None = None
    product_name: str | None = None
    operation_type_code: str
    operation_direction: str
    slot_code: str | None = None
    dock_code: str | None = None
    arrived_at: datetime
    gate_in_at: datetime | None = None
    gate_out_at: datetime | None = None
    dwell_seconds: int
    target_dwell_minutes: int
    blocked_reason_code: str | None = None
    document_number: str | None = None


class VisitDetailOut(VisitOut):
    events: list[VisitEventOut] = []
