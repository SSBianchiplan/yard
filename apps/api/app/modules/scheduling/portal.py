"""Portal do transportador: escopo reduzido, canal próprio, rate limit próprio.

Quem é a transportadora vem de uma credencial, nunca de um código que o cliente digita
(auditoria 2026-10, A7 — antes bastava o cabeçalho `X-Carrier-Code`):

- **chave do portal** (`Authorization: Bearer ypk_…`): gerada pela planta por
  transportadora (`POST /api/v1/catalog/carriers/{id}/portal-key`, só admin), mostrada
  uma vez; o banco guarda só o SHA-256. Gerar de novo revoga a anterior.
- **token do Keycloak** (modo `oidc`): perfil `portal.carrier` + claim `carrier_code`.
- `X-Carrier-Code` puro só vale no modo `open` (desenvolvimento; recusado em produção).

Nada de outra transportadora é exposto, e há teto de chamadas por IP e por
transportadora, mais um teto de credenciais erradas por IP.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.errors import (
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    AppError,
    Forbidden,
    NotFound,
    Unauthenticated,
)
from app.core.ratelimit import SlidingWindowLimiter, client_ip
from app.core.security import Role, principal_from_token
from app.modules.catalog.models import Carrier, Driver, Vehicle
from app.modules.scheduling import service
from app.modules.scheduling.models import Appointment
from app.modules.scheduling.schemas import AppointmentIn, AppointmentOut, ConfirmIn

router = APIRouter(prefix="/portal/v1", tags=["portal"])

PORTAL_KEY_PREFIX = "ypk_"
# Tetos do portal. Um worker só: o contador do processo é o do serviço.
portal_ip_limiter = SlidingWindowLimiter(limit=120, window_seconds=60)
portal_carrier_limiter = SlidingWindowLimiter(limit=60, window_seconds=60)
portal_auth_fail_limiter = SlidingWindowLimiter(limit=10, window_seconds=900)


def hash_portal_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def issue_portal_key(session: AsyncSession, carrier: Carrier) -> tuple[str, datetime]:
    """Gera (ou troca) a chave do portal. Devolve a chave em claro — única vez que ela existe."""
    key = PORTAL_KEY_PREFIX + secrets.token_urlsafe(32)
    carrier.portal_key_hash = hash_portal_key(key)
    carrier.portal_key_issued_at = datetime.now(timezone.utc)
    await session.commit()
    return key, carrier.portal_key_issued_at


async def revoke_portal_key(session: AsyncSession, carrier: Carrier) -> None:
    carrier.portal_key_hash = None
    carrier.portal_key_issued_at = None
    await session.commit()


def _bearer(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


async def _carrier_by_key(session: AsyncSession, key: str) -> Carrier | None:
    digest = hash_portal_key(key)
    carrier = (
        await session.execute(select(Carrier).where(Carrier.portal_key_hash == digest))
    ).scalar_one_or_none()
    # comparação em tempo constante por higiene; a busca já foi pelo hash
    if carrier is None or not hmac.compare_digest(carrier.portal_key_hash or "", digest):
        return None
    return carrier


async def _carrier_by_code(session: AsyncSession, code: str) -> Carrier | None:
    return (
        await session.execute(select(Carrier).where(Carrier.code == code))
    ).scalar_one_or_none()


async def portal_carrier(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_carrier_code: str | None = Header(default=None),
) -> Carrier:
    """Dependência do portal: resolve a transportadora a partir da credencial."""
    ip = client_ip(request)
    portal_ip_limiter.check(f"ip:{ip}", scope="portal")

    carrier: Carrier | None = None
    token = _bearer(authorization)
    try:
        if token.startswith(PORTAL_KEY_PREFIX):
            carrier = await _carrier_by_key(session, token)
        elif token and settings.auth_mode == "oidc":
            principal = await principal_from_token(session, token)
            if Role.PORTAL not in principal.roles or not principal.carrier_code:
                raise Forbidden(ERR_FORBIDDEN, scope="carrier")
            carrier = await _carrier_by_code(session, principal.carrier_code)
        elif settings.auth_mode == "open" and x_carrier_code:
            carrier = await _carrier_by_code(session, x_carrier_code)
    except Unauthenticated:
        carrier = None
    except AppError:
        portal_auth_fail_limiter.check(f"ip:{ip}", scope="portal_auth")
        raise

    if carrier is None:
        # credencial ausente/errada conta para o teto de tentativas do IP
        portal_auth_fail_limiter.check(f"ip:{ip}", scope="portal_auth")
        raise Unauthenticated(ERR_UNAUTHENTICATED, scope="carrier")
    if not carrier.active:
        raise Forbidden(ERR_FORBIDDEN, scope="carrier")
    portal_carrier_limiter.check(f"carrier:{carrier.id}", scope="portal")
    return carrier


async def _ensure_own_resources(
    session: AsyncSession, carrier: Carrier, data: AppointmentIn
) -> None:
    """O agendamento herda a transportadora do VEÍCULO: sem esta checagem, a credencial
    de uma transportadora agendava a placa de outra. Resposta 404, igual a placa
    inexistente, para não confirmar que a placa existe em outra frota."""
    plate = data.plate.strip().upper().replace("-", "")
    vehicle = (
        await session.execute(select(Vehicle).where(Vehicle.plate == plate))
    ).scalar_one_or_none()
    if vehicle is None or vehicle.carrier_id != carrier.id:
        raise NotFound(ERR_NOT_FOUND, entity="vehicle", plate=plate)
    if data.driver_document:
        driver = (
            await session.execute(select(Driver).where(Driver.document == data.driver_document))
        ).scalar_one_or_none()
        if driver is None or driver.carrier_id not in (None, carrier.id):
            raise NotFound(ERR_NOT_FOUND, entity="driver", document=data.driver_document)


@router.get("/appointments", response_model=list[AppointmentOut])
async def my_appointments(
    session: AsyncSession = Depends(get_session),
    carrier: Carrier = Depends(portal_carrier),
) -> list[AppointmentOut]:
    from app.modules.scheduling.router import _projection, _to_out

    rows = (
        await session.execute(
            _projection()
            .where(Appointment.carrier_id == carrier.id)
            .order_by(Appointment.starts_at.desc())
            .limit(200)
        )
    ).all()
    return [_to_out(row) for row in rows]


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
async def self_schedule(
    data: AppointmentIn,
    session: AsyncSession = Depends(get_session),
    carrier: Carrier = Depends(portal_carrier),
) -> AppointmentOut:
    """Auto-agendamento. Nasce como `requested`; confirmar continua sendo ato da planta.

    SLA do contrato: janela pedida com menos de 2h de antecedência não entra pelo portal.
    A transportadora do agendamento é sempre a da credencial, não a do corpo.
    """
    if data.starts_at < service.now() + timedelta(hours=2):
        raise Forbidden("ERR_YARD_PORTAL_LEAD_TIME", minimum_hours=2)
    await _ensure_own_resources(session, carrier, data)
    payload = data.model_copy(update={"channel": "portal", "actor": f"portal:{carrier.code}"})
    appointment = await service.create(session, payload)
    from app.modules.scheduling.router import _reload

    return await _reload(session, appointment.id)


@router.post("/appointments/{appointment_id}/confirm-arrival", response_model=AppointmentOut)
async def confirm_arrival(
    appointment_id: UUID,
    data: ConfirmIn,
    session: AsyncSession = Depends(get_session),
    carrier: Carrier = Depends(portal_carrier),
) -> AppointmentOut:
    """Transportador confirma que vem. Não reserva recurso — só sinaliza intenção."""
    appointment = (
        await session.execute(
            select(Appointment).where(
                Appointment.id == appointment_id, Appointment.carrier_id == carrier.id
            )
        )
    ).scalar_one_or_none()
    if appointment is None:
        raise NotFound(ERR_NOT_FOUND, entity="appointment", id=str(appointment_id))
    # Ator da credencial; vaga é escolha da planta (reserva automática), não do portal.
    data = data.model_copy(update={"actor": f"portal:{carrier.code}", "slot_code": None})
    await service.confirm(session, appointment_id, data)
    from app.modules.scheduling.router import _reload

    return await _reload(session, appointment_id)


@router.get("/availability")
async def portal_availability(
    date_from: datetime | None = None,
    session: AsyncSession = Depends(get_session),
    carrier: Carrier = Depends(portal_carrier),
):
    from app.modules.scheduling.router import availability

    return await availability(session=session, date_from=date_from, hours=48, slot_minutes=60)
