"""Portaria automática: identificar, triar, checar e — só então — comandar o físico.

A ordem importa e é a regra do produto:
    identificação → documentação → checklist → triagem → permissivo do CLP → cancela.
Pular qualquer etapa é abrir cancela no escuro.
"""

import random
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_NOT_FOUND,
    ERR_YARD_CHECKLIST_FAILED,
    ERR_YARD_CHECKLIST_INCOMPLETE,
    ERR_YARD_COMMAND_AI_NOT_APPROVED,
    ERR_YARD_COMMAND_DENIED_BY_PLC,
    ERR_YARD_DEVICE_OFFLINE,
    ERR_YARD_IDENTIFICATION_AMBIGUOUS,
    ERR_YARD_IDENTIFICATION_LOW_CONFIDENCE,
    Conflict,
    NotFound,
)
from app.core.events import hub
from app.modules.catalog.models import Vehicle
from app.modules.gate.models import (
    AccessCommand,
    ChecklistAnswer,
    ChecklistItem,
    ChecklistTemplate,
    Device,
    Escort,
    IdentificationEvent,
)
from app.modules.gate.schemas import (
    ChecklistAnswerIn,
    CommandIn,
    EscortIn,
    IdentifyIn,
    ScreeningOut,
)
from app.modules.scheduling.models import Appointment
from app.modules.visits.models import Visit
from app.modules.yard.models import Gate

# ASSUNÇÃO: leitura de LPR abaixo de 0,85 não libera sozinha — vai para conferência humana.
# O mesmo número está no CHECK da migration; mudar aqui sem mudar lá é inventar um bug.
LPR_THRESHOLD = Decimal("0.85")


def now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_plate(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


async def _one(session: AsyncSession, stmt, entity: str, **params: Any):
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, **params)
    return obj


async def identify(session: AsyncSession, data: IdentifyIn) -> ScreeningOut:
    """Casa a leitura com veículo e agendamento, e decide o destino.

    Não abre nada: devolve a decisão. Abrir cancela é outro ato, com permissivo.
    """
    gate = await _one(
        session, select(Gate).where(Gate.code == data.gate_code), entity="gate", code=data.gate_code
    )

    vehicle = None
    appointment = None
    state = "captured"
    normalized = None
    confidence = data.confidence

    if data.method in ("lpr", "manual", "rfid", "badge"):
        normalized = normalize_plate(data.value)
        candidates = (
            await session.execute(select(Vehicle).where(Vehicle.plate == normalized))
        ).scalars().all()
        if len(candidates) == 1:
            vehicle = candidates[0]
        elif len(candidates) > 1:  # pragma: no cover - placa é única hoje
            state = "ambiguous"
    elif data.method in ("qr", "whatsapp"):
        normalized = data.value.strip().upper()
        appointment = (
            await session.execute(
                select(Appointment).where(Appointment.reference == normalized)
            )
        ).scalar_one_or_none()
        if appointment is not None:
            vehicle = (
                await session.execute(
                    select(Vehicle).where(Vehicle.id == appointment.vehicle_id)
                )
            ).scalar_one_or_none()

    if state != "ambiguous":
        if vehicle is None:
            state = "rejected"
        elif data.method == "lpr" and (confidence is None or confidence < LPR_THRESHOLD):
            # Leitura ruim não vira liberação: vira trabalho para o guarda, com a foto ao lado.
            state = "ambiguous"
        elif data.method == "manual":
            state = "manual_override"
        else:
            state = "matched"

    if appointment is None and vehicle is not None:
        appointment = (
            await session.execute(
                select(Appointment)
                .where(
                    Appointment.vehicle_id == vehicle.id,
                    Appointment.state.in_(("confirmed", "checked_in")),
                )
                .order_by(Appointment.starts_at)
            )
        ).scalars().first()

    event = IdentificationEvent(
        occurred_at=now(),
        gate_id=gate.id,
        method=data.method,
        raw_value=data.value[:120],
        normalized_value=normalized,
        confidence=confidence,
        matched_vehicle_id=vehicle.id if vehicle else None,
        matched_appointment_id=appointment.id if appointment else None,
        state=state,
        image_ref=data.image_ref,
        actor=data.actor,
    )
    session.add(event)
    await session.commit()

    decision = _decide(state, vehicle, appointment)
    await hub.publish(
        "yard.gate.identified",
        {"gate": gate.code, "state": state, "plate": normalized, "decision": decision.decision},
    )

    if state == "ambiguous" and data.method == "lpr":
        raise Conflict(
            ERR_YARD_IDENTIFICATION_LOW_CONFIDENCE,
            value=normalized,
            confidence=float(confidence or 0),
            threshold=float(LPR_THRESHOLD),
        )
    if state == "ambiguous":
        raise Conflict(ERR_YARD_IDENTIFICATION_AMBIGUOUS, value=normalized)
    return decision


def _decide(state: str, vehicle: Vehicle | None, appointment: Appointment | None) -> ScreeningOut:
    """Triagem automática: com agendamento válido tem destino; sem, entra em fila."""
    if state == "rejected" or vehicle is None:
        return ScreeningOut(
            decision="reject", reason_code="ERR_YARD_VEHICLE_UNKNOWN", requires_human=True
        )
    if appointment is None:
        # Sem agendamento não é "não entra": é fila, com decisão humana.
        return ScreeningOut(
            decision="queue",
            reason_code="ERR_YARD_APPOINTMENT_REQUIRED",
            plate=vehicle.plate,
            requires_human=True,
        )
    return ScreeningOut(
        decision="admit",
        plate=vehicle.plate,
        appointment_reference=appointment.reference,
        dock_id=appointment.dock_id,
        requires_human=False,
    )


async def answer_checklist(
    session: AsyncSession, visit_id: UUID, data: ChecklistAnswerIn
) -> list[str]:
    """Responde itens do checklist. Item bloqueante reprovado trava a visita (trigger)."""
    visit = await _one(
        session, select(Visit).where(Visit.id == visit_id), entity="visit", id=str(visit_id)
    )
    failed: list[str] = []
    for answer in data.answers:
        item = await _one(
            session,
            select(ChecklistItem).where(ChecklistItem.id == answer.item_id),
            entity="checklist_item",
            id=str(answer.item_id),
        )
        if item.requires_photo and not answer.passed and not answer.photo_ref:
            raise Conflict(ERR_YARD_CHECKLIST_INCOMPLETE, item=item.code, missing="photo")
        session.add(
            ChecklistAnswer(
                visit_id=visit.id,
                item_id=item.id,
                answered_at=now(),
                passed=answer.passed,
                note=answer.note,
                photo_ref=answer.photo_ref,
                actor=data.actor,
            )
        )
        if not answer.passed and item.severity == "blocking":
            failed.append(item.code)
    await session.commit()
    if failed:
        await hub.publish(
            "yard.gate.checklist_failed", {"visit_id": str(visit_id), "items": failed}
        )
    return failed


async def required_items(session: AsyncSession, visit_id: UUID) -> list[ChecklistItem]:
    """Itens que este veículo precisa responder, pelo tipo de operação e pela carga."""
    visit = await _one(
        session, select(Visit).where(Visit.id == visit_id), entity="visit", id=str(visit_id)
    )
    from app.modules.catalog.models import Product

    hazardous = False
    if visit.product_id:
        product = (
            await session.execute(select(Product).where(Product.id == visit.product_id))
        ).scalar_one_or_none()
        hazardous = bool(product and product.hazardous)

    templates = (
        await session.execute(
            select(ChecklistTemplate).where(
                ChecklistTemplate.active.is_(True),
                ChecklistTemplate.direction.in_(("in", "both")),
            )
        )
    ).scalars().all()
    chosen = [
        template
        for template in templates
        if (not template.hazardous_only or hazardous)
        and (template.operation_type_id in (None, visit.operation_type_id))
    ]
    if not chosen:
        return []
    items = (
        await session.execute(
            select(ChecklistItem)
            .where(ChecklistItem.template_id.in_([t.id for t in chosen]))
            .order_by(ChecklistItem.position)
        )
    ).scalars().all()
    return list(items)


async def read_permissive(session: AsyncSession, device: Device) -> tuple[bool, str]:
    """Lê o permissivo do CLP para este dispositivo, com qualidade.

    Quando há sinal de permissivo mapeado (Fatia 6), ele manda: valor E frescor vêm do
    campo. Sem sinal mapeado, o simulador responde — e nega às vezes, porque a tela
    precisa saber lidar com "o CLP disse não".
    """
    if device.status in ("offline", "maintenance"):
        return False, "no_comm"

    from app.modules.iot import service as iot_service

    value, quality = await iot_service.permissive_for(session, device.code)
    if quality != "no_comm":
        return value, quality

    if device.protocol == "simulator":
        return (random.random() > 0.04), "good"
    return True, "good"


async def command(session: AsyncSession, data: CommandIn) -> AccessCommand:
    """Emite comando físico. Aqui é onde o sistema toca o mundo — e onde ele se segura."""
    device = await _one(
        session,
        select(Device).where(Device.code == data.device_code),
        entity="device",
        code=data.device_code,
    )
    if device.status in ("offline", "maintenance"):
        raise Conflict(ERR_YARD_DEVICE_OFFLINE, device=device.code, status=device.status)

    # Interlock de IA: proposta não aprovada não vira comando. Sem exceção, sem atalho.
    if data.origin == "ai" and not (data.approved_by and data.ai_proposal_id):
        raise Conflict(ERR_YARD_COMMAND_AI_NOT_APPROVED, device=device.code)

    permissive, quality = await read_permissive(session, device)
    cmd = AccessCommand(
        requested_at=now(),
        device_id=device.id,
        gate_id=device.gate_id,
        visit_id=data.visit_id,
        action=data.action,
        origin=data.origin,
        plc_permissive=permissive,
        permissive_quality=quality,
        authorized_by=data.authorized_by,
        approved_by=data.approved_by,
        approved_at=now() if data.approved_by else None,
        ai_proposal_id=data.ai_proposal_id,
        reason_code=data.reason_code,
        state="requested",
    )

    if not permissive or quality != "good":
        cmd.state = "denied_by_plc"
        cmd.failure_code = "PLC_PERMISSIVE_FALSE" if not permissive else "PLC_QUALITY_BAD"
        session.add(cmd)
        await session.commit()
        await hub.publish(
            "yard.gate.command_denied", {"device": device.code, "action": data.action}
        )
        raise Conflict(
            ERR_YARD_COMMAND_DENIED_BY_PLC, device=device.code, quality=quality
        )

    cmd.state = "permitted"
    session.add(cmd)
    await session.flush()

    # Envio ao campo. No simulador o dispositivo confirma na hora; no campo real o ACK
    # chega por evento (Fatia 6) e o comando fica em `sent` até lá.
    cmd.state = "sent"
    if device.protocol == "simulator":
        cmd.state = "acknowledged"
        cmd.acknowledged_at = now()
    device.last_seen_at = now()
    await session.commit()
    await hub.publish(
        "yard.gate.command_sent",
        {"device": device.code, "action": data.action, "state": cmd.state},
    )
    return cmd


async def register_escort(session: AsyncSession, visit_id: UUID, data: EscortIn) -> Escort:
    """Ajudante e visitante entram no sistema como pessoas — é quem a evacuação procura."""
    escort = Escort(
        visit_id=visit_id,
        full_name=data.full_name,
        document=data.document,
        role=data.role,
        entered_at=now(),
    )
    session.add(escort)
    await session.commit()
    return escort


async def self_service_token(session: AsyncSession, appointment_reference: str) -> str:
    """Autoatendimento: o motorista chega com o QR do agendamento.

    O token é o próprio código do agendamento — curto, legível e conferível na guarita
    quando o totem falha (o fallback humano nunca sai de cena).
    """
    appointment = await _one(
        session,
        select(Appointment).where(Appointment.reference == appointment_reference),
        entity="appointment",
        reference=appointment_reference,
    )
    return f"YARD:{appointment.reference}:{date.today().isoformat()}"


async def blocking_failures(session: AsyncSession, visit_id: UUID) -> list[str]:
    """Itens bloqueantes cuja ÚLTIMA conferência reprovou.

    A última é o que vale: o guarda reprova, o motorista corrige, o guarda confere de
    novo. Olhar todas as respostas deixaria o veículo preso para sempre pela primeira
    reprovação — e o histórico continua no banco, para quem audita.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT i.code
                  FROM checklist_item i
                  JOIN LATERAL (
                      SELECT a.passed
                        FROM checklist_answer a
                       WHERE a.visit_id = :visit_id AND a.item_id = i.id
                       ORDER BY a.answered_at DESC
                       LIMIT 1
                  ) last ON true
                 WHERE i.severity = 'blocking' AND last.passed = false
                 ORDER BY i.position
                """
            ),
            {"visit_id": visit_id},
        )
    ).scalars().all()
    return list(rows)


async def ensure_checklist_ok(session: AsyncSession, visit_id: UUID) -> None:
    failures = await blocking_failures(session, visit_id)
    if failures:
        raise Conflict(ERR_YARD_CHECKLIST_FAILED, items=failures)
