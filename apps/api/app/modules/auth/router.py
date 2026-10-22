from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.ratelimit import SlidingWindowLimiter, client_ip
from app.core.security import Principal, Role, current_principal, requires
from app.modules.auth import service
from app.modules.auth.models import AppUser, AuthAudit
from app.modules.auth.schemas import (
    AuthAuditOut,
    ChangePasswordIn,
    LoginIn,
    SessionOut,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
    UserWithPasswordOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(
    prefix="/users", tags=["users"], dependencies=[Depends(requires(Role.ADMIN))]
)


# Bloqueio por conta já existe (auth_max_failed_logins); este é o teto por origem, para
# quem varre muitos e-mails do mesmo IP sem travar nenhuma conta específica.
login_limiter = SlidingWindowLimiter(limit=20, window_seconds=300)


def _ip(request: Request) -> str | None:
    return client_ip(request)


@router.get("/config")
async def auth_config() -> dict[str, str]:
    """O front pergunta como autenticar antes de desenhar a primeira tela."""
    return {"mode": settings.auth_mode}


@router.post("/login", response_model=SessionOut)
async def login(payload: LoginIn, request: Request, session: AsyncSession = Depends(get_session)):
    login_limiter.check(f"ip:{client_ip(request)}", scope="login")
    token, expires, user = await service.login(
        session, payload.email, payload.password, _ip(request)
    )
    return SessionOut(token=token, expires_at=expires, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    user = (
        await session.execute(select(AppUser).where(AppUser.email == principal.subject))
    ).scalar_one_or_none()
    if user is not None:
        return user
    # modo aberto/OIDC: não há linha em app_user, devolve o que o token diz
    return UserOut(
        id=UUID(int=0),
        email=principal.subject,
        name=principal.name,
        roles=sorted(r for r in principal.roles if r != Role.MASTER),
        active=True,
        is_master=Role.MASTER in principal.roles,
        must_change_password=False,
    )


@router.post("/change-password", response_model=UserOut)
async def change_password(
    payload: ChangePasswordIn,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    return await service.change_password(
        session, principal, payload.current_password, payload.new_password
    )


@users_router.get("", response_model=list[UserOut])
async def list_users(session: AsyncSession = Depends(get_session)):
    return await service.list_users(session)


@users_router.post("", response_model=UserWithPasswordOut, status_code=201)
async def create_user(
    payload: UserCreateIn,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    user, temporary = await service.create_user(session, principal, payload)
    return UserWithPasswordOut(user=UserOut.model_validate(user), temporary_password=temporary)


@users_router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    payload: UserUpdateIn,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    return await service.update_user(session, principal, user_id, payload)


@users_router.post("/{user_id}/reset-password", response_model=UserWithPasswordOut)
async def reset_password(
    user_id: UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    user, temporary = await service.reset_password(session, principal, user_id)
    return UserWithPasswordOut(user=UserOut.model_validate(user), temporary_password=temporary)


@users_router.get("/audit", response_model=list[AuthAuditOut])
async def auth_audit(
    session: AsyncSession = Depends(get_session), limit: int = Query(default=200, le=1000)
):
    return (
        (
            await session.execute(
                select(AuthAudit).order_by(AuthAudit.occurred_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
