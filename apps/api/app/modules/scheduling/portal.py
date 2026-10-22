"""Portal do transportador: escopo reduzido, canal próprio, rate limit próprio.

Autenticação real entra com o Keycloak (ver ASSUNCOES #12); até lá o portal aceita o
código da transportadora como identificação e **não** expõe nada de outra transportadora.
"""

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ERR_NOT_FOUND, Forbidden, NotFound
from app.modules.catalog.models import Carrier
from app.modules.scheduling import service
from app.modules.scheduling.models import Appointment
from app.modules.scheduling.schemas import AppointmentIn, AppointmentOut, ConfirmIn

router = APIRouter(prefix="/portal/v1", tags=["portal"])


async def _carrier(session: AsyncSession, code: str | None) -> Carrier:
    if not code:
        raise Forbidden("ERR_FORBIDDEN", scope="carrier")
    carrier = (
        await session.execute(select(Carrier).where(Carrier.code == code))
    ).scalar_one_or_none()
    if carrier is None:
        raise NotFound(ERR_NOT_FOUND, entity="carrier", code=code)
    return carrier


@router.get("/appointments", response_model=list[AppointmentOut])
async def my_appointments(
    session: AsyncSession = Depends(get_session),
    x_carrier_code: str | None = Header(default=None),
) -> list[AppointmentOut]:
    carrier = await _carrier(session, x_carrier_code)
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
    x_carrier_code: str | None = Header(default=None),
) -> AppointmentOut:
    """Auto-agendamento. Nasce como `requested`; confirmar continua sendo ato da planta.

    SLA do contrato: janela pedida com menos de 2h de antecedência não entra pelo portal.
    """
    carrier = await _carrier(session, x_carrier_code)
    if data.starts_at < service.now() + timedelta(hours=2):
        raise Forbidden("ERR_YARD_PORTAL_LEAD_TIME", minimum_hours=2)
    payload = data.model_copy(update={"channel": "portal", "actor": f"portal:{carrier.code}"})
    appointment = await service.create(session, payload)
    from app.modules.scheduling.router import _reload

    return await _reload(session, appointment.id)


@router.post("/appointments/{appointment_id}/confirm-arrival", response_model=AppointmentOut)
async def confirm_arrival(
    appointment_id: UUID,
    data: ConfirmIn,
    session: AsyncSession = Depends(get_session),
    x_carrier_code: str | None = Header(default=None),
) -> AppointmentOut:
    """Transportador confirma que vem. Não reserva recurso — só sinaliza intenção."""
    carrier = await _carrier(session, x_carrier_code)
    appointment = (
        await session.execute(
            select(Appointment).where(
                Appointment.id == appointment_id, Appointment.carrier_id == carrier.id
            )
        )
    ).scalar_one_or_none()
    if appointment is None:
        raise NotFound(ERR_NOT_FOUND, entity="appointment", id=str(appointment_id))
    await service.confirm(session, appointment_id, data)
    from app.modules.scheduling.router import _reload

    return await _reload(session, appointment_id)


@router.get("/availability")
async def portal_availability(
    date_from: datetime | None = None,
    session: AsyncSession = Depends(get_session),
    x_carrier_code: str | None = Header(default=None),
):
    await _carrier(session, x_carrier_code)
    from app.modules.scheduling.router import availability

    return await availability(session=session, date_from=date_from, hours=48, slot_minutes=60)
