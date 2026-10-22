"""Correções da auditoria de segurança de 2026-10.

C1  rotas de doca exigiam nada: agora 401 sem token e 403 sem perfil de doca.
A7  portal do transportador por credencial própria (não por `X-Carrier-Code`) e com teto;
    WebSocket autenticado em `local` e `oidc`, com perfil; ator sempre do token.
M3  PyJWT no lugar do python-jose; algoritmo fixo; papéis só do cliente desta API.
Baixos: /health sem modo de auth/ambiente; /ready sem texto do banco; teto de login por IP;
    YARD_ENV=prod com demonstração declarada (YARD_DEMO).
"""

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core import security
from app.core.config import Settings, settings
from app.core.errors import ERR_YARD_WEIGHT_MANUAL_NEEDS_SECOND_FACTOR, Conflict
from app.core.security import Principal, Role, actor_of, with_actor
from app.modules.auth.models import AppUser
from app.modules.auth.passwords import hash_password, issue_token
from app.modules.catalog.models import Carrier, Vehicle
from app.modules.moves.models import VisitHold
from app.modules.moves.schemas import HoldIn
from app.modules.visits import service as visit_service
from app.modules.visits.schemas import GateInIn, SlotAssignIn

SECRET = "s" * 48


# --------------------------------------------------------------------------- apoio


@pytest.fixture(autouse=True)
def _limiters_zerados():
    from app.modules.auth.router import login_limiter
    from app.modules.scheduling import portal

    for limiter in (
        login_limiter,
        portal.portal_ip_limiter,
        portal.portal_carrier_limiter,
        portal.portal_auth_fail_limiter,
    ):
        limiter.reset()
    yield


@pytest.fixture
def local_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "auth_secret", SECRET)


async def _user(session, email: str, *roles: str) -> dict[str, str]:
    """Usuário local ativo e o cabeçalho com o token dele."""
    user_id = uuid.uuid4()
    session.add(
        AppUser(
            id=user_id,
            email=email,
            name=email,
            password_hash=hash_password("Senha-teste-123"),
            roles=list(roles),
            must_change_password=False,
            created_by="teste",
        )
    )
    await session.commit()
    token, _ = issue_token(email, str(user_id))
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def users_clean(session):
    await session.execute(text("TRUNCATE app_user, auth_audit"))
    await session.commit()
    return session


def _client():
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _visit_in_yard(session) -> uuid.UUID:
    visit = await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A01", driver_document="10000000001", operation_type_code="RECEBIMENTO_GRANEL"
        ),
    )
    visit_id = visit.id
    await visit_service.assign_slot(session, visit_id, SlotAssignIn(slot_code="T-01"))
    return visit_id


# ------------------------------------------------------------- C1: rotas de doca


async def test_c1_docas_sem_token_dao_401(users_clean, fixture_yard, local_mode):
    any_id = uuid.uuid4()
    async with _client() as client:
        assert (await client.get(f"/api/v1/docks/visits/{any_id}/holds")).status_code == 401
        assert (await client.get(f"/api/v1/docks/visits/{any_id}")).status_code == 401
        assert (
            await client.get(f"/api/v1/docks/dock-visits/{any_id}/discrepancies")
        ).status_code == 401
        assert (
            await client.post(f"/api/v1/docks/holds/{any_id}/release", json={})
        ).status_code == 401
        assert (
            await client.post(
                f"/api/v1/docks/visits/{any_id}/holds",
                json={"kind": "quality", "reason_code": "X", "opened_by": "x"},
            )
        ).status_code == 401
        assert (
            await client.post(f"/api/v1/docks/visits/{any_id}/stage", json={"stage": "docked"})
        ).status_code == 401
        assert (
            await client.post(
                f"/api/v1/docks/visits/{any_id}/orders",
                json={"kind": "purchase_order", "external_id": "PO-1"},
            )
        ).status_code == 401


async def test_c1_docas_exigem_perfil(users_clean, fixture_yard, local_mode):
    any_id = uuid.uuid4()
    scale = await _user(users_clean, "balanca@x.com", Role.SCALE)
    scheduler = await _user(users_clean, "agenda@x.com", Role.SCHEDULER)
    dock = await _user(users_clean, "doca@x.com", Role.DOCK)
    async with _client() as client:
        url = f"/api/v1/docks/visits/{any_id}/holds"
        assert (await client.get(url, headers=scale)).status_code == 403
        assert (await client.get(url, headers=scheduler)).status_code == 403
        response = await client.get(url, headers=dock)
        assert response.status_code == 200 and response.json() == []


async def test_c1_ator_da_pendencia_vem_do_token_e_segrega(users_clean, fixture_yard, local_mode):
    """`opened_by`/`released_by` do corpo são ignorados: a segregação deixa de ser burlável."""
    visit_id = await _visit_in_yard(users_clean)
    fiscal = await _user(users_clean, "fiscal@x.com", Role.DOCK)
    supervisor = await _user(users_clean, "supervisor@x.com", Role.SUPERVISOR)
    async with _client() as client:
        opened = await client.post(
            f"/api/v1/docks/visits/{visit_id}/holds",
            headers=fiscal,
            json={"kind": "fiscal", "reason_code": "MISSING_NFE", "opened_by": "outra.pessoa"},
        )
        assert opened.status_code == 201, opened.text
        assert opened.json()["opened_by"] == "fiscal@x.com"
        hold_id = opened.json()["id"]

        # o mesmo usuário, fingindo ser outro no corpo, não libera a própria pendência
        same = await client.post(
            f"/api/v1/docks/holds/{hold_id}/release",
            headers=fiscal,
            json={"released_by": "supervisor@x.com"},
        )
        assert same.status_code == 409
        assert same.json()["error"]["code"] == "ERR_YARD_HOLD_SEGREGATION"

        # cliente antigo que ainda manda o campo, ou cliente novo que não manda: tanto faz
        released = await client.post(
            f"/api/v1/docks/holds/{hold_id}/release", headers=supervisor, json={}
        )
        assert released.status_code == 200, released.text
        assert released.json()["released_by"] == "supervisor@x.com"

    users_clean.expire_all()
    stored = (
        await users_clean.execute(select(VisitHold).where(VisitHold.id == uuid.UUID(hold_id)))
    ).scalar_one()
    assert (stored.opened_by, stored.released_by) == ("fiscal@x.com", "supervisor@x.com")


# ---------------------------------------------------- A7: ator vem do principal


def test_actor_of_ignora_corpo_fora_do_modo_aberto(monkeypatch):
    principal = Principal(subject="guarda@x.com", name="Guarda", roles=frozenset({Role.GATE}))
    monkeypatch.setattr(settings, "auth_mode", "local")
    assert actor_of(principal, "outro.usuario") == "guarda@x.com"
    hold = with_actor(
        HoldIn(kind="quality", reason_code="X", opened_by="outro"), principal, "opened_by"
    )
    assert hold.opened_by == "guarda@x.com"
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    assert actor_of(principal, "outro.usuario") == "guarda@x.com"


async def test_a7_gate_in_registra_o_usuario_do_token(users_clean, fixture_yard, local_mode):
    guard = await _user(users_clean, "guarda@x.com", Role.GATE)
    async with _client() as client:
        response = await client.post(
            "/api/v1/visits/gate-in",
            headers=guard,
            json={
                "plate": "TST1A01",
                "driver_document": "10000000001",
                "operation_type_code": "RECEBIMENTO_GRANEL",
                "actor": "chefe.da.portaria",
            },
        )
        assert response.status_code == 201, response.text
    actors = (
        await users_clean.execute(
            text("SELECT DISTINCT actor FROM visit_event WHERE visit_id = :id"),
            {"id": response.json()["id"]},
        )
    ).scalars().all()
    assert actors == ["guarda@x.com"]


async def test_a7_peso_manual_segundo_fator_nao_e_o_operador(session, fixture_yard):
    from app.modules.weighing import service as weighing
    from app.modules.weighing.schemas import CaptureIn, OpenTicketIn

    visit = await visit_service.gate_in(
        session,
        GateInIn(
            plate="TST1A01", driver_document="10000000001", operation_type_code="RECEBIMENTO_GRANEL"
        ),
    )
    ticket = await weighing.open_ticket(
        session,
        OpenTicketIn(visit_reference=visit.reference, scale_code="SCALE-T1", operator="op@x.com"),
    )
    with pytest.raises(Conflict) as exc:
        await weighing.capture(
            session,
            ticket.id,
            CaptureIn(
                kind="gross",
                manual_weight_kg=30000,
                reason_code="SCALE_DOWN",
                operator="op@x.com",
                second_factor_user="OP@x.com",
            ),
        )
    assert exc.value.code == ERR_YARD_WEIGHT_MANUAL_NEEDS_SECOND_FACTOR


# ------------------------------------------------- A7: portal do transportador


async def _second_carrier(session) -> None:
    other_id = uuid.uuid4()
    session.add(Carrier(id=other_id, code="T-OUTRA", name="Outra Log"))
    await session.flush()
    session.add(Vehicle(id=uuid.uuid4(), plate="OUT1A01", kind="truck", carrier_id=other_id))
    await session.commit()


async def test_a7_portal_codigo_puro_nao_autentica(users_clean, fixture_yard, local_mode):
    async with _client() as client:
        response = await client.get(
            "/portal/v1/appointments", headers={"X-Carrier-Code": "T-TRA"}
        )
        assert response.status_code == 401
        assert (await client.get("/portal/v1/availability")).status_code == 401
        forged = {"Authorization": "Bearer ypk_chave-inventada"}
        assert (await client.get("/portal/v1/appointments", headers=forged)).status_code == 401


async def test_a7_portal_chave_por_transportadora(users_clean, fixture_yard, local_mode):
    await _second_carrier(users_clean)
    admin = await _user(users_clean, "admin@x.com", Role.ADMIN)
    scheduler = await _user(users_clean, "agenda@x.com", Role.SCHEDULER)
    carrier_id = fixture_yard["carrier"]
    async with _client() as client:
        # só administrador emite chave
        url = f"/api/v1/catalog/carriers/{carrier_id}/portal-key"
        assert (await client.post(url, headers=scheduler)).status_code == 403
        issued = await client.post(url, headers=admin)
        assert issued.status_code == 201
        key = issued.json()["portal_key"]
        assert key.startswith("ypk_") and len(key) > 40
        portal = {"Authorization": f"Bearer {key}"}

        mine = await client.get("/portal/v1/appointments", headers=portal)
        assert mine.status_code == 200 and mine.json() == []

        # a credencial de uma transportadora não agenda a placa de outra
        starts = datetime.now(UTC) + timedelta(days=1)
        other = await client.post(
            "/portal/v1/appointments",
            headers=portal,
            json={
                "dock_code": "DOCK-T1",
                "plate": "OUT1A01",
                "operation_type_code": "RECEBIMENTO_GRANEL",
                "starts_at": starts.isoformat(),
                "ends_at": (starts + timedelta(hours=1)).isoformat(),
            },
        )
        assert other.status_code == 404

        # o banco guarda só o hash
        stored = (
            await users_clean.execute(
                select(Carrier.portal_key_hash).where(Carrier.id == carrier_id)
            )
        ).scalar_one()
        assert stored and key not in stored and len(stored) == 64

        # reemitir revoga a anterior; revogar derruba tudo
        reissued = (await client.post(url, headers=admin)).json()["portal_key"]
        assert (await client.get("/portal/v1/appointments", headers=portal)).status_code == 401
        new_portal = {"Authorization": f"Bearer {reissued}"}
        assert (await client.get("/portal/v1/appointments", headers=new_portal)).status_code == 200
        assert (await client.delete(url, headers=admin)).status_code == 204
        assert (
            await client.get("/portal/v1/appointments", headers=new_portal)
        ).status_code == 401


async def test_a7_portal_oidc_exige_perfil_e_claim(users_clean, fixture_yard, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_audience", "yard-api")
    claims = {
        "good": {
            "sub": "1",
            "preferred_username": "trans",
            "realm_access": {"roles": ["portal.carrier"]},
            "carrier_code": "T-TRA",
        },
        "no-claim": {"sub": "2", "realm_access": {"roles": ["portal.carrier"]}},
        "no-role": {"sub": "3", "realm_access": {"roles": []}, "carrier_code": "T-TRA"},
    }
    monkeypatch.setattr(security, "_decode", lambda token: claims[token])
    async with _client() as client:
        ok = await client.get(
            "/portal/v1/appointments", headers={"Authorization": "Bearer good"}
        )
        assert ok.status_code == 200
        for token in ("no-claim", "no-role"):
            response = await client.get(
                "/portal/v1/appointments", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 403


async def test_a7_portal_teto_de_credencial_errada(users_clean, fixture_yard, local_mode):
    async with _client() as client:
        codes = [
            (
                await client.get(
                    "/portal/v1/appointments", headers={"Authorization": "Bearer ypk_errada"}
                )
            ).status_code
            for _ in range(12)
        ]
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]


# --------------------------------------------------------- A7: WebSocket da torre


@pytest.fixture
def ws_app(monkeypatch):
    """App com o barramento trocado por uma mensagem só: o socket aceita, entrega e fecha."""
    from app import main

    async def one_message():
        yield '{"type":"ping"}'

    monkeypatch.setattr(main.hub, "subscribe", one_message)
    return main.app


def _ws_outcome(app, subprotocols=None) -> str:
    client = TestClient(app)
    try:
        with client.websocket_connect("/ws/yard", subprotocols=subprotocols or []) as ws:
            return ws.receive_text()
    except WebSocketDisconnect as exc:
        return f"closed:{exc.code}"


def test_a7_ws_oidc_sem_token_recusado(ws_app, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_audience", "yard-api")
    monkeypatch.setattr(
        security,
        "_decode",
        lambda token: {
            "ctrl": {"sub": "c", "realm_access": {"roles": ["yard.controller"]}},
            "carrier": {"sub": "p", "realm_access": {"roles": ["portal.carrier"]}},
            # papel de MESMO nome em outro cliente do realm não vale aqui
            "other-client": {
                "sub": "o",
                "resource_access": {"outro-app": {"roles": ["yard.admin"]}},
            },
        }[token],
    )
    assert _ws_outcome(ws_app) == "closed:1008"
    assert _ws_outcome(ws_app, ["yard.bearer", "carrier"]) == "closed:1008"
    assert _ws_outcome(ws_app, ["yard.bearer", "other-client"]) == "closed:1008"
    assert _ws_outcome(ws_app, ["yard.bearer", "ctrl"]) == '{"type":"ping"}'


def test_a7_ws_local_exige_token_e_perfil(ws_app, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "auth_secret", SECRET)
    people = {
        "gate": Principal(subject="g", name="g", roles=frozenset({Role.GATE})),
        "device": Principal(subject="d", name="d", roles=frozenset({Role.DEVICE})),
    }

    async def fake_local(_session, token):
        if token not in people:
            from app.core.errors import Unauthenticated

            raise Unauthenticated("ERR_UNAUTHENTICATED")
        return people[token]

    monkeypatch.setattr(security, "principal_from_local_token", fake_local)
    assert _ws_outcome(ws_app) == "closed:1008"
    assert _ws_outcome(ws_app, ["yard.bearer", "inventado"]) == "closed:1008"
    assert _ws_outcome(ws_app, ["yard.bearer", "device"]) == "closed:1008"
    assert _ws_outcome(ws_app, ["yard.bearer", "gate"]) == '{"type":"ping"}'


# ------------------------------------------------------------- M3: PyJWT / OIDC


class _FakeJwks:
    def __init__(self, public_key):
        self._key = public_key

    def get_signing_key_from_jwt(self, _token):
        return type("K", (), {"key": self._key})()


@pytest.fixture
def rsa_keys(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(security, "_jwks_client", lambda: _FakeJwks(private.public_key()))
    monkeypatch.setattr(settings, "oidc_issuer", "https://sso.exemplo/realms/yard")
    monkeypatch.setattr(settings, "oidc_audience", "yard-api")
    return private


def _claims(**over):
    base = {
        "sub": "u1",
        "iss": "https://sso.exemplo/realms/yard",
        "aud": "yard-api",
        "exp": int(time.time()) + 300,
        "preferred_username": "op",
        "realm_access": {"roles": ["yard.gate"]},
        "resource_access": {
            "yard-api": {"roles": ["yard.scale"]},
            "outro-app": {"roles": ["yard.admin"]},
        },
    }
    base.update(over)
    return base


def test_m3_oidc_valida_e_le_so_o_cliente_da_api(rsa_keys):
    token = jwt.encode(_claims(), rsa_keys, algorithm="RS256")
    principal = security._principal_from_claims(security._decode(token))
    assert principal.subject == "op"
    assert principal.roles == frozenset({"yard.gate", "yard.scale"})  # sem o admin de outro app


@pytest.mark.parametrize(
    "mutate",
    [
        {"aud": "outro-app"},
        {"iss": "https://atacante/realms/yard"},
        {"exp": int(time.time()) - 3600},
    ],
)
def test_m3_oidc_recusa_audiencia_emissor_validade(rsa_keys, mutate):
    from app.core.errors import Unauthenticated

    token = jwt.encode(_claims(**mutate), rsa_keys, algorithm="RS256")
    with pytest.raises(Unauthenticated):
        security._decode(token)


def test_m3_oidc_recusa_hs256_e_none(rsa_keys):
    """Confusão de algoritmo: o servidor só aceita RS256, nunca o `alg` do cabeçalho."""
    from app.core.errors import Unauthenticated

    hs = jwt.encode(_claims(), "segredo-qualquer-com-32-bytes-ou-mais!!", algorithm="HS256")
    none = jwt.encode(_claims(), None, algorithm="none")
    for token in (hs, none):
        with pytest.raises(Unauthenticated):
            security._decode(token)


def test_m3_python_jose_fora_das_dependencias():
    import importlib.util
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    deps = " ".join(pyproject["project"]["dependencies"]).lower()
    assert "python-jose" not in deps and "pyjwt" in deps
    assert importlib.util.find_spec("jose") is None


# ------------------------------------------------- baixos: health, ready, login, config


async def test_health_nao_expoe_modo_fora_de_dev(monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    async with _client() as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
    monkeypatch.setattr(settings, "env", "dev")
    async with _client() as client:
        assert "auth_mode" in (await client.get("/health")).json()


async def test_login_tem_teto_por_ip(users_clean, monkeypatch, local_mode):
    from app.modules.auth.router import login_limiter

    monkeypatch.setattr(login_limiter, "limit", 3)
    async with _client() as client:
        codes = [
            (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": f"ninguem{i}@x.com", "password": "qualquer-123"},
                )
            ).status_code
            for i in range(5)
        ]
    assert codes == [401, 401, 401, 429, 429]


def _prod(**over) -> Settings:
    base = dict(
        env="prod",
        auth_mode="local",
        auth_secret="z" * 48,
        database_url="postgresql+asyncpg://app:segredo@localhost/yard",
        cors_origins="https://yard.exemplo.com",
        field_mode="simulator",
    )
    base.update(over)
    return Settings(_env_file=None, **base)


def test_prod_com_demonstracao_declarada():
    demo = _prod(demo=True)
    assert demo.is_production and demo.simulators_enabled
    with pytest.raises(ValueError, match="YARD_FIELD_MODE"):
        _prod(demo=False)
    with pytest.raises(ValueError, match="YARD_AUTH_SECRET"):
        _prod(demo=True, auth_secret="dev-inseguro-troque-em-producao-mas-longo")
    with pytest.raises(ValueError, match="YARD_AUTH_MODE"):
        _prod(demo=True, auth_mode="open")
