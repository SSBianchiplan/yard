from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApproveIn(BaseModel):
    approved_by: str = Field(min_length=2, max_length=120)
    note: str | None = None


class RejectIn(BaseModel):
    rejected_by: str = Field(min_length=2, max_length=120)
    reason_code: str = Field(min_length=2, max_length=48)
    note: str | None = None


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str
    kind: str
    state: str
    created_at: datetime
    expires_at: datetime
    rationale: str
    impact_json: dict
    payload_json: dict
    confidence: Decimal | None
    model_version: str | None
    approved_by: str | None
    approved_at: datetime | None
    rejected_reason_code: str | None
    executed_at: datetime | None
    execution_result: str | None


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decided_at: datetime
    decided_by: str
    decision: str
    reason_code: str | None
    note: str | None


class BottleneckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    detected_at: datetime
    scope: str
    scope_ref: str | None
    severity: str
    metric: str
    value: Decimal
    threshold: Decimal
    state: str
    acknowledged_by: str | None
    acknowledged_at: datetime | None


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurred_at: datetime
    visit_id: UUID
    predicted_release_at: datetime
    confidence: Decimal | None
    model_version: str | None


class TowerOverviewOut(BaseModel):
    gate_queue: int
    in_yard: int
    over_dwell: int
    demurrage_risk: int
    docks_busy: int
    docks_total: int
    late_appointments: int
    open_moves: int
    open_holds: int
    alarms: int
    pending_proposals: int
