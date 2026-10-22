"""Pesagem: bruto, tara, líquido — e as regras que impedem o número de mentir.

O que este módulo protege, em ordem de importância:
  1. o líquido é derivado, nunca digitado;
  2. captura só vale com peso estável e veículo posicionado;
  3. peso manual exige justificativa e um segundo humano;
  4. ticket fechado não muda — e carrega hash para provar;
  5. divergência contra a NF-e acima da tolerância bloqueia a saída.
"""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_NOT_FOUND,
    ERR_YARD_SCALE_OFFLINE,
    ERR_YARD_TICKET_CLOSED,
    ERR_YARD_TICKET_IMMUTABLE,
    ERR_YARD_WEIGHT_MANUAL_NEEDS_SECOND_FACTOR,
    ERR_YARD_WEIGHT_REENTRY_SUSPECT,
    ERR_YARD_WEIGHT_TARE_ABOVE_GROSS,
    ERR_YARD_WEIGHT_UNSTABLE,
    ERR_YARD_WEIGHT_VEHICLE_MISPLACED,
    Conflict,
    NotFound,
)
from app.core.events import hub
from app.modules.catalog.models import Vehicle
from app.modules.visits.models import Visit
from app.modules.weighing.drivers import ScaleSample, driver_for
from app.modules.weighing.models import (
    AxleWeight,
    ScaleReading,
    TareRecord,
    WeighingCapture,
    WeighingReprint,
    WeighingTicket,
)
from app.modules.weighing.schemas import (
    CaptureIn,
    CloseTicketIn,
    OpenTicketIn,
    ReprintIn,
)
from app.modules.yard.models import Scale

# ASSUNÇÃO: reentrada da mesma placa na mesma balança em menos de 10 min é suspeita.
REENTRY_WINDOW = timedelta(minutes=10)
# ASSUNÇÃO: tara aferida que difere mais de 3% da cadastral marca o ticket para conferência.
TARE_DRIFT_PCT = Decimal("3.0")


def now() -> datetime:
    return datetime.now(timezone.utc)


async def _one(session: AsyncSession, stmt, entity: str, **params: Any):
    obj = (await session.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise NotFound(ERR_NOT_FOUND, entity=entity, **params)
    return obj


async def live_reading(session: AsyncSession, scale_code: str) -> ScaleSample:
    """Leitura corrente do indicador, persistida como telemetria."""
    scale = await _one(
        session, select(Scale).where(Scale.code == scale_code), entity="scale", code=scale_code
    )
    if scale.status in ("offline", "maintenance"):
        raise Conflict(ERR_YARD_SCALE_OFFLINE, scale=scale.code, status=scale.status)

    driver = driver_for(scale.code, scale.protocol, scale.endpoint)
    sample = await driver.read()
    session.add(
        ScaleReading(
            occurred_at=sample.occurred_at,
            scale_id=scale.id,
            weight_kg=sample.weight_kg,
            stable=sample.stable,
            quality=sample.quality,
            vehicle_positioned=None,
            source="simulator" if scale.protocol == "simulator" else "device",
        )
    )
    await session.commit()
    return sample


async def open_ticket(session: AsyncSession, data: OpenTicketIn) -> WeighingTicket:
    visit = await _one(
        session,
        select(Visit).where(Visit.reference == data.visit_reference),
        entity="visit",
        reference=data.visit_reference,
    )
    scale = await _one(
        session,
        select(Scale).where(Scale.code == data.scale_code),
        entity="scale",
        code=data.scale_code,
    )
    vehicle = await _one(
        session, select(Vehicle).where(Vehicle.id == visit.vehicle_id), entity="vehicle"
    )

    # Reentrada suspeita: mesma placa, mesma balança, intervalo curto.
    recent = (
        await session.execute(
            select(WeighingTicket)
            .where(
                WeighingTicket.vehicle_id == vehicle.id,
                WeighingTicket.scale_id == scale.id,
                WeighingTicket.closed_at.is_not(None),
                WeighingTicket.closed_at > now() - REENTRY_WINDOW,
            )
            .order_by(WeighingTicket.closed_at.desc())
        )
    ).scalars().first()
    if recent is not None and not data.reentry_justified:
        raise Conflict(
            ERR_YARD_WEIGHT_REENTRY_SUSPECT, plate=vehicle.plate, previous=recent.reference
        )

    seq = (await session.execute(text("SELECT nextval('weighing_ticket_seq')"))).scalar_one()
    ticket = WeighingTicket(
        plant_id=visit.plant_id,
        reference=f"WGH-{date.today().year}-{seq:06d}",
        state="open",
        visit_id=visit.id,
        vehicle_id=vehicle.id,
        scale_id=scale.id,
        product_id=visit.product_id,
        mode=data.mode,
        document_number=data.document_number or visit.document_number,
        document_net_kg=data.document_net_kg,
        tolerance_pct=Decimal(str(data.tolerance_pct)),
        operator=data.operator,
    )
    if data.mode == "fixed_tare":
        # Tara cadastral: rápida, e por isso mesmo a que mais erra. Fica marcada como tal.
        ticket.tare_kg = vehicle.tare_kg
        ticket.tare_source = "registered"
        ticket.tare_at = now()
    session.add(ticket)
    await session.commit()
    await hub.publish("yard.weighing.opened", {"reference": ticket.reference})
    return ticket


async def capture(session: AsyncSession, ticket_id: UUID, data: CaptureIn) -> WeighingTicket:
    """Captura o peso do indicador. Instável ou mal posicionado não vira ticket."""
    ticket = await _get(session, ticket_id)
    if ticket.state in ("closed", "cancelled"):
        raise Conflict(ERR_YARD_TICKET_CLOSED, reference=ticket.reference)

    scale = await _one(session, select(Scale).where(Scale.id == ticket.scale_id), entity="scale")

    if data.manual_weight_kg is not None:
        # Caminho de exceção: peso digitado. Exige motivo e um segundo humano autorizado.
        if not data.reason_code or not data.second_factor_user:
            raise Conflict(
                ERR_YARD_WEIGHT_MANUAL_NEEDS_SECOND_FACTOR, reference=ticket.reference
            )
        sample = ScaleSample(
            weight_kg=data.manual_weight_kg, stable=True, occurred_at=now(), quality="good"
        )
        source = "manual"
        ticket.source = "manual"
        ticket.reason_code = data.reason_code
        ticket.second_factor_user = data.second_factor_user
    else:
        driver = driver_for(scale.code, scale.protocol, scale.endpoint)
        sample = await driver.read()
        source = "simulator" if scale.protocol == "simulator" else "device"
        if sample.quality != "good":
            raise Conflict(ERR_YARD_SCALE_OFFLINE, scale=scale.code, quality=sample.quality)
        if not sample.stable:
            raise Conflict(
                ERR_YARD_WEIGHT_UNSTABLE, scale=scale.code, weight_kg=sample.weight_kg
            )
        if not data.vehicle_positioned:
            # Laço indutivo / fotocélula dizem que o veículo não está inteiro na plataforma.
            raise Conflict(ERR_YARD_WEIGHT_VEHICLE_MISPLACED, scale=scale.code)

    session.add(
        WeighingCapture(
            ticket_id=ticket.id,
            occurred_at=sample.occurred_at,
            kind=data.kind,
            weight_kg=sample.weight_kg,
            stable=sample.stable,
            vehicle_positioned=data.vehicle_positioned,
            image_ref=data.image_ref,
            operator=data.operator,
            source=source,
        )
    )

    # Coerência bruto × tara antes de gravar: o CHECK do banco pega isso, mas
    # devolveria "violação de integridade" — que não diz ao balanceiro o que houve.
    # Tara maior que o bruto costuma ser caminhão ainda carregado na segunda pesagem.
    if data.kind == "tare" and ticket.gross_kg is not None:
        if sample.weight_kg > ticket.gross_kg:
            raise Conflict(
                ERR_YARD_WEIGHT_TARE_ABOVE_GROSS,
                tare_kg=sample.weight_kg,
                gross_kg=ticket.gross_kg,
            )
    if data.kind == "gross" and ticket.tare_kg is not None:
        if sample.weight_kg < ticket.tare_kg:
            raise Conflict(
                ERR_YARD_WEIGHT_TARE_ABOVE_GROSS,
                tare_kg=ticket.tare_kg,
                gross_kg=sample.weight_kg,
            )

    if data.kind == "gross":
        ticket.gross_kg = sample.weight_kg
        ticket.gross_at = sample.occurred_at
        ticket.state = "first_weight" if ticket.tare_kg is None else "second_weight"
    elif data.kind == "tare":
        ticket.tare_kg = sample.weight_kg
        ticket.tare_at = sample.occurred_at
        ticket.tare_source = "measured"
        ticket.state = "second_weight" if ticket.gross_kg is not None else "first_weight"
        session.add(
            TareRecord(
                vehicle_id=ticket.vehicle_id,
                measured_at=sample.occurred_at,
                tare_kg=sample.weight_kg,
                scale_id=ticket.scale_id,
                ticket_id=ticket.id,
            )
        )
    else:  # axle
        session.add(
            AxleWeight(
                ticket_id=ticket.id,
                axle_number=data.axle_number or 1,
                weight_kg=sample.weight_kg,
            )
        )

    if ticket.image_ref is None and data.image_ref:
        ticket.image_ref = data.image_ref

    await session.commit()
    await hub.publish(
        "yard.weighing.captured",
        {"reference": ticket.reference, "kind": data.kind, "weight_kg": sample.weight_kg},
    )
    return ticket


def _hash(ticket: WeighingTicket) -> str:
    """Hash canônico do que importa. Muda um número, muda o hash — e isso é o ponto."""
    payload = {
        "reference": ticket.reference,
        "visit_id": str(ticket.visit_id),
        "vehicle_id": str(ticket.vehicle_id),
        "scale_id": str(ticket.scale_id),
        "gross_kg": ticket.gross_kg,
        "tare_kg": ticket.tare_kg,
        "net_kg": ticket.net_kg,
        "tare_source": ticket.tare_source,
        "gross_at": ticket.gross_at.isoformat() if ticket.gross_at else None,
        "tare_at": ticket.tare_at.isoformat() if ticket.tare_at else None,
        "document_number": ticket.document_number,
        "document_net_kg": ticket.document_net_kg,
        "source": ticket.source,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def close_ticket(
    session: AsyncSession, ticket_id: UUID, data: CloseTicketIn
) -> WeighingTicket:
    ticket = await _get(session, ticket_id)
    if ticket.state == "closed":
        raise Conflict(ERR_YARD_TICKET_IMMUTABLE, reference=ticket.reference)
    if ticket.gross_kg is None or ticket.tare_kg is None:
        raise Conflict(ERR_YARD_TICKET_CLOSED, reference=ticket.reference, missing="weights")
    if ticket.image_ref is None and data.image_ref is None:
        # CHECK do banco também recusa; aqui o erro sai traduzível.
        raise Conflict(ERR_YARD_TICKET_CLOSED, reference=ticket.reference, missing="image")

    ticket.image_ref = ticket.image_ref or data.image_ref
    ticket.net_kg = ticket.gross_kg - ticket.tare_kg
    if data.document_number:
        ticket.document_number = data.document_number
    if data.document_net_kg is not None:
        ticket.document_net_kg = data.document_net_kg

    if ticket.document_net_kg:
        ticket.divergence_kg = ticket.net_kg - ticket.document_net_kg
        ticket.divergence_pct = (
            Decimal(ticket.divergence_kg) / Decimal(ticket.document_net_kg) * Decimal(100)
        ).quantize(Decimal("0.001"))

    ticket.closed_at = now()
    ticket.state = "closed"
    ticket.integrity_hash = _hash(ticket)
    reference = ticket.reference
    await session.commit()
    # O trigger yard_weighing_block_exit já marcou a visita se a divergência estourou.
    await hub.publish(
        "yard.weighing.closed",
        {"reference": reference, "net_kg": ticket.net_kg, "hash": ticket.integrity_hash},
    )
    return ticket


async def reprint(session: AsyncSession, ticket_id: UUID, data: ReprintIn) -> WeighingTicket:
    """Reimprimir é permitido; reimprimir sem deixar rastro, não."""
    ticket = await _get(session, ticket_id)
    session.add(
        WeighingReprint(
            ticket_id=ticket.id, occurred_at=now(), actor=data.actor, reason_code=data.reason_code
        )
    )
    ticket.reprint_count += 1
    await session.commit()
    return ticket


async def tare_drift(session: AsyncSession, ticket: WeighingTicket) -> Decimal | None:
    """Quanto a tara aferida difere da cadastral, em %."""
    if ticket.tare_kg is None or ticket.tare_source != "measured":
        return None
    vehicle = await _one(
        session, select(Vehicle).where(Vehicle.id == ticket.vehicle_id), entity="vehicle"
    )
    if not vehicle.tare_kg:
        return None
    return (
        (Decimal(ticket.tare_kg) - Decimal(vehicle.tare_kg))
        / Decimal(vehicle.tare_kg)
        * Decimal(100)
    ).quantize(Decimal("0.001"))


async def _get(session: AsyncSession, ticket_id: UUID) -> WeighingTicket:
    return await _one(
        session,
        select(WeighingTicket).where(WeighingTicket.id == ticket_id),
        entity="weighing_ticket",
        id=str(ticket_id),
    )
