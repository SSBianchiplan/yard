"""Simulador de campo — permite desenvolver 100% do sistema sem hardware.

Emite eventos como se viessem de LPR, balança, cancela e laço indutivo. Dois modos:

    python -m app.simulator --rate 12                          # direto no banco (rápido)
    python -m app.simulator --rate 12 --api http://host:8088   # pela API (como um device)

O modo `--api` é o que faz as telas se mexerem sozinhas: o barramento de eventos é
in-process (ver ASSUNCOES #13), então só o que passa pelo processo da API chega ao
WebSocket da torre. Um dispositivo de campo real também fala HTTP/MQTT com o servidor,
não com o banco — então este é o modo fiel; o modo direto existe para popular rápido.

Nas Fatias 3/4/6 este módulo ganhou os alvos de balança, a leitura de placa e o tick de
campo; o contrato de chamada continua o mesmo.
"""

import argparse
import asyncio
import random
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.db import SessionLocal
from app.modules.visits import service
from app.modules.visits.schemas import DockAssignIn, GateInIn, GateOutIn, SlotAssignIn

random.seed()


async def _pick(session, query: str) -> dict | None:
    row = (await session.execute(text(query))).mappings().first()
    return dict(row) if row else None


FREE_VEHICLE = """
    SELECT v.plate, d.document FROM vehicle v
    JOIN driver d ON d.carrier_id = v.carrier_id
      AND (d.license_expires_on IS NULL OR d.license_expires_on > current_date)
    WHERE NOT EXISTS (
        SELECT 1 FROM visit x WHERE x.vehicle_id = v.id
        AND x.state IN ('at_gate_in','in_yard','at_dock','at_gate_out'))
    ORDER BY random() LIMIT 1
"""


async def one_cycle(*, full: bool = True) -> str:
    """Uma visita inteira, direto no domínio: chega → vaga → doca → sai."""
    async with SessionLocal() as session:
        vehicle = await _pick(session, FREE_VEHICLE)
        if vehicle is None:
            return "sem veículo livre"
        operation = await _pick(session, "SELECT code FROM operation_type ORDER BY random() LIMIT 1")

        # LPR falso: 8% de leitura duvidosa vira digitação de exceção, como no campo real.
        source = "device" if random.random() > 0.08 else "manual"
        visit = await service.gate_in(
            session,
            GateInIn(
                plate=vehicle["plate"],
                driver_document=vehicle["document"],
                operation_type_code=operation["code"],
                gate_code="GATE-01",
                source=source,
                actor="simulator",
            ),
        )
        if not full:
            return f"{visit.reference} chegou ({source})"

        await asyncio.sleep(random.uniform(0.2, 0.8))
        await service.assign_slot(session, visit.id, SlotAssignIn(source="simulator", actor="sim"))

        dock = await _pick(
            session, "SELECT code FROM dock WHERE status = 'available' ORDER BY random() LIMIT 1"
        )
        if dock:
            await asyncio.sleep(random.uniform(0.2, 0.8))
            await service.assign_dock(
                session, visit.id, DockAssignIn(dock_code=dock["code"], source="simulator")
            )

        await asyncio.sleep(random.uniform(0.3, 1.2))
        await service.gate_out(session, visit.id, GateOutIn(gate_code="GATE-02", source="simulator"))
        return f"{visit.reference} ciclo completo"


async def one_cycle_http(client, base: str, *, full: bool = True) -> str:
    """Mesmo ciclo, pela API — é assim que a torre vê o pátio mexer em tempo real."""
    async with SessionLocal() as session:
        vehicle = await _pick(session, FREE_VEHICLE)
        operation = await _pick(session, "SELECT code FROM operation_type ORDER BY random() LIMIT 1")
    if vehicle is None:
        return "sem veículo livre"

    source = "device" if random.random() > 0.08 else "manual"
    response = await client.post(
        f"{base}/api/v1/visits/gate-in",
        json={
            "plate": vehicle["plate"],
            "driver_document": vehicle["document"],
            "operation_type_code": operation["code"],
            "gate_code": "GATE-01",
            "source": source,
            "actor": "simulator",
        },
    )
    if response.status_code >= 400:
        return f"gate-in recusado: {response.json().get('error', {}).get('code', response.status_code)}"
    visit = response.json()
    reference, visit_id = visit["reference"], visit["id"]

    if not full:
        return f"{reference} chegou ({source})"

    await asyncio.sleep(random.uniform(0.3, 1.0))
    slot = await client.post(
        f"{base}/api/v1/visits/{visit_id}/slot", json={"source": "simulator", "actor": "sim"}
    )
    if slot.status_code >= 400:
        return f"{reference} sem vaga: {slot.json().get('error', {}).get('code')}"

    await asyncio.sleep(random.uniform(0.4, 1.2))
    async with SessionLocal() as session:
        dock = await _pick(
            session, "SELECT code FROM dock WHERE status = 'available' ORDER BY random() LIMIT 1"
        )
    if dock:
        await client.post(
            f"{base}/api/v1/visits/{visit_id}/dock",
            json={"dock_code": dock["code"], "source": "simulator"},
        )

    await asyncio.sleep(random.uniform(0.5, 1.5))
    await client.post(
        f"{base}/api/v1/visits/{visit_id}/gate-out",
        json={"gate_code": "GATE-02", "source": "simulator"},
    )
    return f"{reference} ciclo completo (via API)"


async def _api_client(base: str):
    """Cliente HTTP do simulador. Com `YARD_SIM_EMAIL`/`YARD_SIM_PASSWORD`, entra como
    usuário de serviço — com a API em modo `local`, evento sem token é recusado."""
    import os

    import httpx

    client = httpx.AsyncClient(timeout=10)
    email, password = os.environ.get("YARD_SIM_EMAIL"), os.environ.get("YARD_SIM_PASSWORD")
    if email and password:
        response = await client.post(
            f"{base}/api/v1/auth/login", json={"email": email, "password": password}
        )
        response.raise_for_status()
        client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    return client


async def run(rate_per_minute: int, api_base: str | None) -> None:
    interval = 60 / max(1, rate_per_minute)
    where = f"pela API {api_base}" if api_base else "direto no banco"
    print(
        f"simulador de campo ativo — {rate_per_minute} chegadas/min, {where} (ctrl+c encerra)",
        flush=True,
    )

    client = None
    logged_at = time.monotonic()
    if api_base:
        client = await _api_client(api_base)

    try:
        while True:
            try:
                if client is not None:
                    # token vence em horas e o simulador roda por dias: renova antes
                    if time.monotonic() - logged_at > 3 * 3600:
                        await client.aclose()
                        client = await _api_client(api_base)
                        logged_at = time.monotonic()
                    result = await one_cycle_http(client, api_base)
                else:
                    result = await one_cycle()
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {result}", flush=True)
            except Exception as exc:  # simulador não pode derrubar a sessão de trabalho
                print(f"[sim] ignorado: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(interval)
    finally:
        if client is not None:
            await client.aclose()


def main() -> None:
    from app.core.config import settings

    if settings.is_production:
        raise SystemExit(
            "simulador recusado: YARD_ENV=prod. Em produção o pátio fala com CLP, "
            "balança e câmera de verdade — evento inventado aqui vira trilha de "
            "auditoria falsa lá."
        )

    parser = argparse.ArgumentParser(description="Simulador de campo do YARD")
    parser.add_argument("--rate", type=int, default=12, help="chegadas por minuto")
    parser.add_argument("--once", action="store_true", help="executa um ciclo e sai")
    parser.add_argument("--arrival-only", action="store_true", help="só gate-in, deixa em fila")
    parser.add_argument(
        "--api",
        metavar="URL",
        help="fala com a API em vez do banco — é o modo que faz a tela se mexer",
    )
    args = parser.parse_args()
    # stdout sem buffer: log de simulador que só aparece no fim não serve para nada.
    sys.stdout.reconfigure(line_buffering=True)

    if args.once or args.arrival_only:
        full = not args.arrival_only
        if args.api:

            async def single() -> str:
                client = await _api_client(args.api)
                async with client:
                    return await one_cycle_http(client, args.api, full=full)

            print(asyncio.run(single()))
        else:
            print(asyncio.run(one_cycle(full=full)))
    else:
        asyncio.run(run(args.rate, args.api))


if __name__ == "__main__":
    main()
