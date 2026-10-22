"""Login, senha e gestão de usuários do modo `local`.

Segregação que a tela não consegue contornar:
  - só o master cria, edita ou redefine a senha de outro administrador;
  - ninguém desativa a si mesmo nem tira o próprio `yard.admin` (evita trancar-se fora);
  - o master em si é protegido no banco (migration 0013), não só aqui.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    ERR_NOT_FOUND,
    AppError,
    Conflict,
    Forbidden,
    NotFound,
    Unauthenticated,
)
from app.core.security import Principal, Role
from app.modules.auth.models import AppUser, AuthAudit
from app.modules.auth.passwords import (
    hash_password,
    issue_token,
    password_problem,
    temporary_password,
    verify_password,
)
from app.modules.auth.schemas import UserCreateIn, UserUpdateIn

ERR_AUTH_INVALID_CREDENTIALS = "ERR_AUTH_INVALID_CREDENTIALS"
ERR_AUTH_LOCKED = "ERR_AUTH_LOCKED"
ERR_AUTH_WEAK_PASSWORD = "ERR_AUTH_WEAK_PASSWORD"
ERR_AUTH_MASTER_PROTECTED = "ERR_AUTH_MASTER_PROTECTED"
ERR_AUTH_ADMIN_REQUIRES_MASTER = "ERR_AUTH_ADMIN_REQUIRES_MASTER"
ERR_AUTH_SELF_LOCKOUT = "ERR_AUTH_SELF_LOCKOUT"
ERR_AUTH_EMAIL_TAKEN = "ERR_AUTH_EMAIL_TAKEN"

# Hash de uma senha qualquer: usuário inexistente paga o mesmo scrypt que o existente,
# e o tempo de resposta não vira oráculo de "este e-mail tem conta".
_DUMMY_HASH = hash_password("usuario-inexistente-0")


def _now() -> datetime:
    return datetime.now(UTC)


async def audit(
    session: AsyncSession,
    event_type: str,
    *,
    actor: str | None,
    target_email: str | None = None,
    ip: str | None = None,
    **payload: Any,
) -> None:
    session.add(
        AuthAudit(
            event_type=event_type, actor=actor, target_email=target_email, ip=ip, payload=payload
        )
    )


async def _by_email(session: AsyncSession, email: str) -> AppUser | None:
    return (
        await session.execute(select(AppUser).where(func.lower(AppUser.email) == email.lower()))
    ).scalar_one_or_none()


async def _get(session: AsyncSession, user_id) -> AppUser:
    user = await session.get(AppUser, user_id)
    if user is None:
        raise NotFound(ERR_NOT_FOUND, entity="app_user", id=str(user_id))
    return user


def _check_strength(password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise AppError(ERR_AUTH_WEAK_PASSWORD, reason=problem)


async def login(session: AsyncSession, email: str, password: str, ip: str | None):
    user = await _by_email(session, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        await audit(
            session, "login_failed", actor=None, target_email=email, ip=ip, reason="unknown"
        )
        await session.commit()
        raise Unauthenticated(ERR_AUTH_INVALID_CREDENTIALS)

    if user.locked_until and user.locked_until > _now():
        await audit(session, "login_locked", actor=None, target_email=user.email, ip=ip)
        await session.commit()
        raise Unauthenticated(ERR_AUTH_LOCKED, until=user.locked_until.isoformat())

    if not user.active or not verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= settings.auth_max_failed_logins:
            user.locked_until = _now() + timedelta(minutes=settings.auth_lock_minutes)
            user.failed_logins = 0
        await audit(
            session,
            "login_failed",
            actor=None,
            target_email=user.email,
            ip=ip,
            reason="inactive" if not user.active else "password",
        )
        await session.commit()
        raise Unauthenticated(ERR_AUTH_INVALID_CREDENTIALS)

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = _now()
    await audit(session, "login", actor=user.email, target_email=user.email, ip=ip)
    await session.commit()
    token, expires = issue_token(user.email, str(user.id))
    return token, expires, user


async def change_password(
    session: AsyncSession, principal: Principal, current: str, new: str
) -> AppUser:
    user = await _by_email(session, principal.subject)
    if user is None or not verify_password(current, user.password_hash):
        raise Unauthenticated(ERR_AUTH_INVALID_CREDENTIALS)
    _check_strength(new)
    if verify_password(new, user.password_hash):
        raise AppError(ERR_AUTH_WEAK_PASSWORD, reason="same_as_current")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    user.password_changed_at = _now()
    await audit(session, "password_changed", actor=user.email, target_email=user.email)
    await session.commit()
    return user


def _guard_admin_target(
    principal: Principal, target_is_admin: bool, target_is_master: bool
) -> None:
    actor_is_master = Role.MASTER in principal.roles
    if target_is_master and not actor_is_master:
        raise Forbidden(ERR_AUTH_MASTER_PROTECTED)
    if target_is_admin and not actor_is_master:
        raise Forbidden(ERR_AUTH_ADMIN_REQUIRES_MASTER)


async def list_users(session: AsyncSession) -> list[AppUser]:
    return list(
        (await session.execute(select(AppUser).order_by(AppUser.is_master.desc(), AppUser.name)))
        .scalars()
        .all()
    )


async def create_user(session: AsyncSession, principal: Principal, data: UserCreateIn):
    _guard_admin_target(principal, Role.ADMIN in data.roles, False)
    if await _by_email(session, data.email):
        raise Conflict(ERR_AUTH_EMAIL_TAKEN, email=data.email)
    temporary = None
    if data.password:
        _check_strength(data.password)
        password = data.password
    else:
        password = temporary = temporary_password()
    user = AppUser(
        email=data.email,
        name=data.name.strip(),
        roles=data.roles,
        password_hash=hash_password(password),
        must_change_password=True,
        created_by=principal.subject,
    )
    session.add(user)
    await audit(
        session, "user_created", actor=principal.subject, target_email=data.email, roles=data.roles
    )
    await session.commit()
    return user, temporary


async def update_user(session: AsyncSession, principal: Principal, user_id, data: UserUpdateIn):
    user = await _get(session, user_id)
    grants_admin = data.roles is not None and Role.ADMIN in data.roles
    _guard_admin_target(principal, Role.ADMIN in user.roles or grants_admin, user.is_master)

    is_self = user.email == principal.subject
    if is_self and data.active is False:
        raise AppError(ERR_AUTH_SELF_LOCKOUT)
    if is_self and data.roles is not None and Role.ADMIN in user.roles and not grants_admin:
        raise AppError(ERR_AUTH_SELF_LOCKOUT)
    if user.is_master and (data.active is False or (data.roles is not None and not grants_admin)):
        raise Conflict(ERR_AUTH_MASTER_PROTECTED)

    changes: dict[str, Any] = {}
    if data.name is not None and data.name.strip() != user.name:
        changes["name"] = [user.name, data.name.strip()]
        user.name = data.name.strip()
    if data.roles is not None and data.roles != sorted(user.roles):
        changes["roles"] = [sorted(user.roles), data.roles]
        user.roles = data.roles
    if data.active is not None and data.active != user.active:
        changes["active"] = [user.active, data.active]
        user.active = data.active
    if changes:
        await audit(
            session, "user_updated", actor=principal.subject, target_email=user.email, **changes
        )
    await session.commit()
    return user


async def reset_password(session: AsyncSession, principal: Principal, user_id):
    user = await _get(session, user_id)
    if user.email != principal.subject:
        _guard_admin_target(principal, Role.ADMIN in user.roles, user.is_master)
    temporary = temporary_password()
    user.password_hash = hash_password(temporary)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    await audit(session, "password_reset", actor=principal.subject, target_email=user.email)
    await session.commit()
    return user, temporary


async def ensure_master(session: AsyncSession) -> str | None:
    """Garante o admin master configurado em `YARD_MASTER_EMAIL`.

    Idempotente: se já existe, não toca na senha (a do banco vale). Devolve o e-mail
    quando criou, para o boot registrar no log.
    """
    email = (settings.master_email or "").strip().lower()
    if not email:
        return None
    existing = await _by_email(session, email)
    if existing is not None:
        if not existing.is_master:
            current_master = (
                await session.execute(select(AppUser).where(AppUser.is_master))
            ).scalar_one_or_none()
            if current_master is None:
                existing.is_master = True
                existing.active = True
                existing.roles = sorted(set(existing.roles) | {Role.ADMIN})
                await audit(session, "master_promoted", actor="system", target_email=email)
                await session.commit()
        return None
    if not settings.master_password:
        raise SystemExit("defina YARD_MASTER_PASSWORD para criar o admin master")
    _check_strength(settings.master_password)
    session.add(
        AppUser(
            email=email,
            name=settings.master_name,
            roles=[Role.ADMIN],
            password_hash=hash_password(settings.master_password),
            is_master=True,
            must_change_password=False,
            created_by="system",
        )
    )
    await audit(session, "master_created", actor="system", target_email=email)
    await session.commit()
    return email
