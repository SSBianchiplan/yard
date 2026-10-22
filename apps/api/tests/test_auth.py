"""Usuários locais: login, bloqueio, segregação de admin e o master intocável no banco."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import settings
from app.core.errors import AppError, Forbidden, Unauthenticated
from app.core.security import Principal, Role
from app.modules.auth import service
from app.modules.auth.models import AppUser
from app.modules.auth.passwords import hash_password, verify_password
from app.modules.auth.schemas import UserCreateIn, UserUpdateIn

MASTER = "master@exemplo.com"
MASTER_PASSWORD = "Master-senha-2026"


@pytest_asyncio.fixture
async def users(session, monkeypatch):
    await session.execute(text("TRUNCATE app_user, auth_audit"))
    await session.commit()
    monkeypatch.setattr(settings, "master_email", MASTER)
    monkeypatch.setattr(settings, "master_password", MASTER_PASSWORD)
    assert await service.ensure_master(session) == MASTER
    return session


def _principal(email: str, *roles: str) -> Principal:
    return Principal(subject=email, name=email, roles=frozenset(roles))


MASTER_P = _principal(MASTER, Role.ADMIN, Role.MASTER)


def test_hash_roundtrip_e_salt():
    first, second = hash_password("abc123defg"), hash_password("abc123defg")
    assert first != second
    assert verify_password("abc123defg", first)
    assert not verify_password("abc123defh", first)


async def test_master_criado_uma_vez_e_login(users):
    # idempotente: segunda chamada não recria nem troca senha
    assert await service.ensure_master(users) is None
    token, _, user = await service.login(users, MASTER, MASTER_PASSWORD, "127.0.0.1")
    assert token and user.is_master and Role.ADMIN in user.roles


async def test_senha_errada_bloqueia_apos_limite(users):
    for _ in range(settings.auth_max_failed_logins):
        with pytest.raises(Unauthenticated):
            await service.login(users, MASTER, "errada-123456", None)
    with pytest.raises(Unauthenticated) as locked:
        await service.login(users, MASTER, MASTER_PASSWORD, None)
    assert locked.value.code == "ERR_AUTH_LOCKED"


async def test_email_inexistente_mesmo_erro(users):
    with pytest.raises(Unauthenticated) as exc:
        await service.login(users, "ninguem@x.com", "qualquer-123", None)
    assert exc.value.code == "ERR_AUTH_INVALID_CREDENTIALS"


async def test_admin_comum_nao_cria_admin(users):
    admin = _principal("admin@x.com", Role.ADMIN)
    with pytest.raises(Forbidden):
        await service.create_user(
            users, admin, UserCreateIn(email="novo@x.com", name="Novo", roles=[Role.ADMIN])
        )
    user, temporary = await service.create_user(
        users, admin, UserCreateIn(email="Guarda@X.com", name="Guarda", roles=[Role.GATE])
    )
    assert user.email == "guarda@x.com" and user.must_change_password and temporary


async def test_ninguem_se_tranca_fora(users):
    master = (await users.execute(text("SELECT id FROM app_user"))).scalar_one()
    with pytest.raises(AppError):
        await service.update_user(users, MASTER_P, master, UserUpdateIn(active=False))
    with pytest.raises(AppError):
        await service.update_user(users, MASTER_P, master, UserUpdateIn(roles=[Role.GATE]))


async def test_banco_protege_master_mesmo_por_sql_cru(users):
    with pytest.raises((IntegrityError, DBAPIError)):
        await users.execute(text("UPDATE app_user SET active = false WHERE is_master"))
    await users.rollback()
    with pytest.raises((IntegrityError, DBAPIError)):
        await users.execute(text("DELETE FROM app_user WHERE is_master"))
    await users.rollback()
    with pytest.raises((IntegrityError, DBAPIError)):
        await users.execute(
            text(
                "INSERT INTO app_user (email, name, password_hash, roles, is_master)"
                " VALUES ('outro@x.com', 'Outro', 'x', '{yard.admin}', true)"
            )
        )
    await users.rollback()


async def test_perfil_desconhecido_recusado_no_banco(users):
    with pytest.raises((IntegrityError, DBAPIError)):
        await users.execute(
            text(
                "INSERT INTO app_user (email, name, password_hash, roles)"
                " VALUES ('x@x.com', 'X', 'x', '{yard.superuser}')"
            )
        )
    await users.rollback()


async def test_trilha_de_acesso_append_only(users):
    await service.login(users, MASTER, MASTER_PASSWORD, None)
    with pytest.raises((IntegrityError, DBAPIError)):
        await users.execute(text("DELETE FROM auth_audit"))
    await users.rollback()


async def test_troca_de_senha_exige_atual_e_forca(users):
    principal = _principal(MASTER, Role.ADMIN, Role.MASTER)
    with pytest.raises(Unauthenticated):
        await service.change_password(users, principal, "errada-000000", "Nova-senha-99")
    with pytest.raises(AppError) as weak:
        await service.change_password(users, principal, MASTER_PASSWORD, "curta1")
    assert weak.value.code == "ERR_AUTH_WEAK_PASSWORD"
    await service.change_password(users, principal, MASTER_PASSWORD, "Nova-senha-99")
    await service.login(users, MASTER, "Nova-senha-99", None)


async def test_http_modo_local_exige_token_e_revoga_desativado(users, monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "auth_secret", "x" * 48)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/api/v1/yard/map")).status_code == 401

        login = await client.post(
            "/api/v1/auth/login", json={"email": MASTER, "password": MASTER_PASSWORD}
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        assert (await client.get("/api/v1/auth/me", headers=headers)).json()["is_master"]

        created = await client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": "op@x.com", "name": "Operador", "roles": ["yard.gate"]},
        )
        assert created.status_code == 201
        temporary = created.json()["temporary_password"]
        op_login = await client.post(
            "/api/v1/auth/login", json={"email": "op@x.com", "password": temporary}
        )
        op_headers = {"Authorization": f"Bearer {op_login.json()['token']}"}
        # operador de guarita não administra usuários
        assert (await client.get("/api/v1/users", headers=op_headers)).status_code == 403

        await client.patch(
            f"/api/v1/users/{created.json()['user']['id']}",
            headers=headers,
            json={"active": False},
        )
        # token ainda válido no relógio, mas o usuário foi desativado: acesso cai na hora
        assert (await client.get("/api/v1/auth/me", headers=op_headers)).status_code == 401

    user = (
        await users.execute(text("SELECT count(*) FROM app_user WHERE NOT active"))
    ).scalar_one()
    assert user == 1
    assert AppUser.__tablename__ == "app_user"
