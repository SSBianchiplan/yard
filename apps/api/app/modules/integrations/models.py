from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class IntegrationEndpoint(PkMixin, TimestampMixin, Base):
    __tablename__ = "integration_endpoint"

    code: Mapped[str] = mapped_column(String(48), unique=True)
    system: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8), default="out")
    url: Mapped[str | None] = mapped_column(String(300))
    auth_kind: Mapped[str] = mapped_column(String(24), default="none")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_retry: Mapped[int] = mapped_column(default=8)


class OutboxMessage(PkMixin, Base):
    """Outbox transacional: a mensagem nasce junto do fato, na mesma transação.

    Se o commit do fato passou, a mensagem existe. Se não passou, nenhuma das duas existe.
    É esse "ou tudo ou nada" que evita ERP e pátio contando histórias diferentes.
    """

    __tablename__ = "outbox_message"

    created_at: Mapped[datetime]
    endpoint_id: Mapped[UUID | None] = mapped_column(ForeignKey("integration_endpoint.id"))
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[UUID]
    # timestamp em milissegundos não cabe em int32 — a coluna é bigint
    event_seq: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retry: Mapped[int] = mapped_column(default=8)
    next_attempt_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
    acknowledged_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(String(300))


class InboxMessage(PkMixin, Base):
    __tablename__ = "inbox_message"

    received_at: Mapped[datetime]
    endpoint_id: Mapped[UUID | None] = mapped_column(ForeignKey("integration_endpoint.id"))
    external_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16), default="received")
    processed_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(String(300))


class ApiRequest(PkMixin, Base):
    """Registro de idempotência: mesma chave do mesmo cliente devolve a mesma resposta."""

    __tablename__ = "api_request"

    created_at: Mapped[datetime]
    client_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(240))
    status_code: Mapped[int | None]
    response_json: Mapped[dict | None] = mapped_column(JSONB)


class FiscalDocument(PkMixin, Base):
    """NF-e, CT-e, MDF-e, romaneio, ordem de coleta — termos próprios, não traduzidos."""

    __tablename__ = "fiscal_document"

    visit_id: Mapped[UUID | None] = mapped_column(ForeignKey("visit.id"))
    kind: Mapped[str] = mapped_column(String(16))
    access_key: Mapped[str | None] = mapped_column(String(44))
    number: Mapped[str | None] = mapped_column(String(32))
    series: Mapped[str | None] = mapped_column(String(8))
    issuer_tax_id: Mapped[str | None] = mapped_column(String(32))
    net_weight_kg: Mapped[int | None]
    state: Mapped[str] = mapped_column(String(16), default="received")
    validated_at: Mapped[datetime | None]
    rejection_code: Mapped[str | None] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class NotificationOptOut(PkMixin, Base):
    __tablename__ = "notification_optout"

    channel: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(160))
    opted_out_at: Mapped[datetime]
    reason_code: Mapped[str | None] = mapped_column(String(48))


class Notification(PkMixin, Base):
    """Aviso ao motorista/transportadora, com log de entrega e opt-out respeitado."""

    __tablename__ = "notification"

    created_at: Mapped[datetime]
    visit_id: Mapped[UUID | None] = mapped_column(ForeignKey("visit.id"))
    appointment_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointment.id"))
    channel: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(160))
    template_code: Mapped[str] = mapped_column(String(48))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(16), default="queued")
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None]
    delivered_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]
    failure_code: Mapped[str | None] = mapped_column(String(48))
    provider_message_id: Mapped[str | None] = mapped_column(String(120))


class DeliveryLog(PkMixin, Base):
    __tablename__ = "delivery_log"

    notification_id: Mapped[UUID] = mapped_column(ForeignKey("notification.id"))
    occurred_at: Mapped[datetime]
    state: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str | None] = mapped_column(String(300))
