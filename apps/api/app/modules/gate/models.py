from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, PkMixin, TimestampMixin


class Device(PkMixin, TimestampMixin, Base):
    """Dispositivo de campo. A Fatia 6 pendura saúde e sinais aqui; a 4 já comanda."""

    __tablename__ = "device"

    plant_id: Mapped[UUID] = mapped_column(ForeignKey("plant.id"))
    code: Mapped[str] = mapped_column(String(48), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    gate_id: Mapped[UUID | None] = mapped_column(ForeignKey("gate.id"))
    dock_id: Mapped[UUID | None] = mapped_column(ForeignKey("dock.id"))
    scale_id: Mapped[UUID | None] = mapped_column(ForeignKey("scale.id"))
    protocol: Mapped[str] = mapped_column(String(24), default="simulator")
    endpoint: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="online")
    last_seen_at: Mapped[datetime | None]


class IdentificationEvent(PkMixin, Base):
    """Toda identificação vira evento: LPR, QR, RFID, crachá ou digitação de exceção.

    A digitação não é "erro do sistema", é caminho previsto — e contado no KPI.
    """

    __tablename__ = "identification_event"

    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    gate_id: Mapped[UUID] = mapped_column(ForeignKey("gate.id"))
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("device.id"))
    method: Mapped[str] = mapped_column(String(16))
    raw_value: Mapped[str | None] = mapped_column(String(120))
    normalized_value: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    matched_vehicle_id: Mapped[UUID | None] = mapped_column(ForeignKey("vehicle.id"))
    matched_appointment_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointment.id"))
    visit_id: Mapped[UUID | None] = mapped_column(ForeignKey("visit.id"))
    state: Mapped[str] = mapped_column(String(24), default="captured")
    image_ref: Mapped[str | None] = mapped_column(String(240))
    actor: Mapped[str | None] = mapped_column(String(120))


class ChecklistTemplate(PkMixin, TimestampMixin, Base):
    __tablename__ = "checklist_template"

    code: Mapped[str] = mapped_column(String(48), unique=True)
    direction: Mapped[str] = mapped_column(String(16), default="in")
    operation_type_id: Mapped[UUID | None] = mapped_column(ForeignKey("operation_type.id"))
    hazardous_only: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ChecklistItem(PkMixin, Base):
    """Item é código estável; o texto do item vive no i18n da tela."""

    __tablename__ = "checklist_item"

    template_id: Mapped[UUID] = mapped_column(ForeignKey("checklist_template.id"))
    code: Mapped[str] = mapped_column(String(48))
    position: Mapped[int]
    severity: Mapped[str] = mapped_column(String(16), default="blocking")
    requires_photo: Mapped[bool] = mapped_column(Boolean, default=False)


class ChecklistAnswer(PkMixin, Base):
    __tablename__ = "checklist_answer"

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    item_id: Mapped[UUID] = mapped_column(ForeignKey("checklist_item.id"))
    answered_at: Mapped[datetime]
    passed: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(String(240))
    photo_ref: Mapped[str | None] = mapped_column(String(240))
    actor: Mapped[str] = mapped_column(String(120))


class AccessCommand(PkMixin, Base):
    """Comando físico. O sistema NÃO substitui função de segurança.

    Sai apenas com permissivo do CLP verdadeiro e fresco, com autorizador identificado, e
    — se a origem for IA — com aprovação humana registrada. Os três invariantes moram no
    banco, porque é lá que ninguém consegue "esquecer" deles.
    """

    __tablename__ = "access_command"

    requested_at: Mapped[datetime]
    device_id: Mapped[UUID] = mapped_column(ForeignKey("device.id"))
    gate_id: Mapped[UUID | None] = mapped_column(ForeignKey("gate.id"))
    visit_id: Mapped[UUID | None] = mapped_column(ForeignKey("visit.id"))
    action: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(24), default="requested")
    origin: Mapped[str] = mapped_column(String(16), default="human")
    plc_permissive: Mapped[bool | None] = mapped_column(Boolean)
    permissive_quality: Mapped[str | None] = mapped_column(String(16))
    authorized_by: Mapped[str | None] = mapped_column(String(120))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None]
    ai_proposal_id: Mapped[UUID | None]
    reason_code: Mapped[str | None] = mapped_column(String(48))
    acknowledged_at: Mapped[datetime | None]
    failure_code: Mapped[str | None] = mapped_column(String(48))


class Escort(PkMixin, Base):
    """Acompanhante, ajudante, visitante: entram na lista de emergência como gente."""

    __tablename__ = "escort"

    visit_id: Mapped[UUID] = mapped_column(ForeignKey("visit.id"))
    full_name: Mapped[str] = mapped_column(String(160))
    document: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(24), default="helper")
    entered_at: Mapped[datetime]
    exited_at: Mapped[datetime | None]
