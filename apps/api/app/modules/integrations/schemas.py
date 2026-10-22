from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EndpointIn(BaseModel):
    code: str
    system: str = Field(
        pattern="^(sap_b1|sap_hana|odoo|opcenter|wms|tms|pcp|bi|webhook|notification)$"
    )
    direction: str = Field(default="out", pattern="^(in|out|both)$")
    url: str | None = None
    auth_kind: str = Field(default="none", pattern="^(none|basic|bearer|hmac|oauth2)$")
    active: bool = True
    max_retry: int = 8


class OutboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    state: str
    retry_count: int
    max_retry: int
    next_attempt_at: datetime
    sent_at: datetime | None
    last_error: str | None
    payload: dict


class FiscalDocumentIn(BaseModel):
    kind: str = Field(pattern="^(nfe|cte|mdfe|packing_list|collection_order)$")
    visit_id: UUID | None = None
    access_key: str | None = None  # 44 dígitos para NF-e/CT-e/MDF-e
    number: str | None = None
    series: str | None = None
    issuer_tax_id: str | None = None
    net_weight_kg: int | None = None
    payload: dict[str, Any] = {}


class FiscalDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    access_key: str | None
    number: str | None
    state: str
    net_weight_kg: int | None
    validated_at: datetime | None
    rejection_code: str | None


class NotificationIn(BaseModel):
    channel: str = Field(pattern="^(whatsapp|sms|email|app|voice)$")
    address: str
    template_code: str
    visit_id: UUID | None = None
    appointment_id: UUID | None = None
    params: dict[str, Any] = {}


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel: str
    address: str
    template_code: str
    state: str
    opted_out: bool
    created_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None
    failure_code: str | None
