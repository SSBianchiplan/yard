"""Autenticação e segregação de função.

Em produção, identidade vem do token do Keycloak — nunca de uma string que o cliente
manda. Antes disso, todo `actor` no sistema era autodeclarado: bastava trocar o JSON para
assinar uma liberação de cancela como outra pessoa.

Perfis (§3.11 do spec): quem agenda ≠ quem libera ≠ quem pesa ≠ quem aprova exceção.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.errors import ERR_FORBIDDEN, ERR_UNAUTHENTICATED, Forbidden, Unauthenticated


class Role:
    SCHEDULER = "yard.scheduler"
    GATE = "yard.gate"
    SCALE = "yard.scale"
    SPOTTER = "yard.spotter"
    DOCK = "yard.dock"
    SUPERVISOR = "yard.supervisor"
    CONTROLLER = "yard.controller"
    ADMIN = "yard.admin"
    PORTAL = "portal.carrier"
    DEVICE = "yard.device"
    # Sintético: não se atribui, deriva de `app_user.is_master`. Só ele mexe em admins.
    MASTER = "yard.master"


@dataclass(frozen=True)
class Principal:
    """Quem está agindo. `subject` vira o `actor` de toda trilha de auditoria."""

    subject: str
    name: str
    roles: frozenset[str] = field(default_factory=frozenset)
    carrier_code: str | None = None

    def has(self, *roles: str) -> bool:
        return Role.ADMIN in self.roles or any(role in self.roles for role in roles)


bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    """Chaves públicas do realm, cacheadas em processo (antes: baixadas a cada pedido).

    O `PyJWKClient` guarda o JWKS por `lifespan` segundos e, quando chega um `kid`
    desconhecido (rotação no Keycloak), busca o conjunto de novo uma vez.
    """
    return jwt.PyJWKClient(settings.oidc_jwks_url, cache_jwk_set=True, lifespan=600, timeout=5)


def _decode(token: str) -> dict[str, Any]:
    """Valida o token do Keycloak: assinatura RS256, emissor, audiência e validade.

    PyJWT no lugar do python-jose (auditoria 2026-10, M3): o jose estava sem manutenção
    e arrastava o `ecdsa` (CVE-2024-23342). O algoritmo continua fixo — nunca o do
    cabeçalho do token.
    """
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.oidc_audience or None,
            issuer=settings.oidc_issuer,
            options={
                "verify_aud": bool(settings.oidc_audience),
                "require": ["exp", "iss", "sub"],
            },
            leeway=30,
        )
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise Unauthenticated(ERR_UNAUTHENTICATED, reason="invalid_token") from exc


def _principal_from_claims(claims: dict[str, Any]) -> Principal:
    """Perfis do realm + perfis do cliente DESTA API, e só dela.

    Antes somávamos os papéis de todos os clientes em `resource_access`: um papel de
    mesmo nome dado em outro aplicativo do realm virava permissão aqui.
    """
    realm_roles = set(claims.get("realm_access", {}).get("roles", []))
    client_roles: set[str] = set()
    if settings.oidc_audience:
        own = claims.get("resource_access", {}).get(settings.oidc_audience, {})
        client_roles.update(own.get("roles", []))
    carrier_code = claims.get("carrier_code")
    return Principal(
        subject=claims.get("preferred_username") or claims.get("sub", "unknown"),
        name=claims.get("name") or claims.get("preferred_username") or "unknown",
        # MASTER é sintético (só do banco local); token externo não o concede.
        roles=frozenset((realm_roles | client_roles) - {Role.MASTER}),
        carrier_code=str(carrier_code) if carrier_code else None,
    )


async def principal_from_local_token(session: AsyncSession, token: str) -> Principal:
    """Modo `local`: o token só diz quem é; perfil e situação vêm do banco, agora.

    Reler a cada requisição custa uma consulta por chave primária e compra o que importa:
    usuário desativado ou com perfil retirado perde o acesso na hora, não quando o token
    vencer daqui a 12 horas.
    """
    from uuid import UUID

    from app.modules.auth.models import AppUser
    from app.modules.auth.passwords import decode_token

    claims = decode_token(token)
    try:
        user_id = UUID(str(claims.get("uid")))
    except ValueError as exc:
        raise Unauthenticated(ERR_UNAUTHENTICATED, reason="invalid_token") from exc
    user = await session.get(AppUser, user_id)
    if user is None or not user.active:
        raise Unauthenticated(ERR_UNAUTHENTICATED, reason="inactive")
    roles = set(user.roles) | ({Role.MASTER} if user.is_master else set())
    return Principal(subject=user.email, name=user.name, roles=frozenset(roles))


async def current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """Resolve quem está agindo.

    Fora de produção, `YARD_AUTH_MODE=open` deixa passar com um perfil de desenvolvimento
    identificado como tal — e o modo `open` é **recusado** quando `YARD_ENV=prod`
    (ver `Settings.validate_production`), para ninguém subir aberto sem perceber.
    """
    if settings.auth_mode == "open":
        return Principal(
            subject=request.headers.get("X-Dev-Actor", "dev.local"),
            name="Desenvolvimento",
            roles=frozenset({Role.ADMIN, Role.MASTER}),
        )

    if credentials is None or not credentials.credentials:
        raise Unauthenticated(ERR_UNAUTHENTICATED, reason="missing_token")
    return await principal_from_token(session, credentials.credentials)


async def principal_from_token(session: AsyncSession, token: str) -> Principal:
    """Token → quem é, nos dois modos autenticados. Usado pela API e pelo WebSocket."""
    if not token:
        raise Unauthenticated(ERR_UNAUTHENTICATED, reason="missing_token")
    if settings.auth_mode == "local":
        return await principal_from_local_token(session, token)
    if settings.auth_mode == "oidc":
        return _principal_from_claims(_decode(token))
    raise Unauthenticated(ERR_UNAUTHENTICATED, reason="invalid_token")


# Perfis que operam o pátio e podem assinar o canal ao vivo (WebSocket/SSE). O evento
# carrega placa e visita: portal de transportadora e dispositivo de campo ficam de fora.
LIVE_FEED_ROLES = (
    Role.GATE,
    Role.SCALE,
    Role.SPOTTER,
    Role.DOCK,
    Role.SUPERVISOR,
    Role.CONTROLLER,
    Role.SCHEDULER,
)


def requires(*roles: str):
    """Dependência de rota que exige um dos perfis."""

    async def guard(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has(*roles):
            raise Forbidden(ERR_FORBIDDEN, required=list(roles), subject=principal.subject)
        return principal

    return guard


def actor_of(principal: Principal, declared: str | None = None) -> str:
    """O ator de uma ação é sempre o token.

    `declared` existe só para o caso de dispositivo de campo que se identifica no corpo
    (por exemplo o simulador em dev); com token presente, ele é ignorado — quem assina a
    trilha é quem autenticou.
    """
    if settings.auth_mode == "open" and declared:
        return declared
    return principal.subject


def with_actor(data, principal: Principal, *fields: str):
    """Cópia do corpo com os campos de ator (`actor`, `approved_by`, …) vindos do token.

    O cliente pode continuar mandando esses campos (compatibilidade com o front e com
    integrações antigas), mas o valor é descartado: assina a trilha quem autenticou.
    """
    return data.model_copy(
        update={name: actor_of(principal, getattr(data, name, None)) for name in fields}
    )
