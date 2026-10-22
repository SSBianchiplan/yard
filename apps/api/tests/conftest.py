"""Testes rodam contra um Postgres real: EXCLUDE, trigger e CHECK são o que estamos testando.

    docker compose up -d db
    YARD_DATABASE_URL=postgresql+asyncpg://yard:yard@localhost:5442/yard_test pytest
"""

import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import insert, text

os.environ.setdefault(
    "YARD_DATABASE_URL", "postgresql+asyncpg://yard:yard@localhost:5442/yard_test"
)

from app.core.db import SessionLocal, engine  # noqa: E402
import app.models  # noqa: F401,E402  (registra o metadata completo)
from app.modules.catalog.models import Carrier, Driver, OperationType, Plant, Vehicle  # noqa: E402
from app.modules.yard.models import Dock, Gate, Scale, Slot, Zone  # noqa: E402


# Windows: o Proactor derruba conexões asyncpg no fim do loop; o Selector não.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest_asyncio.fixture
async def session():
    """Cada teste tem seu próprio loop: a engine é descartada no fim para não
    reaproveitar conexão de um loop já fechado."""
    async with SessionLocal() as s:
        await s.execute(
            text(
                "TRUNCATE delivery_log, notification, notification_optout, fiscal_document,"
                " api_request, inbox_message, outbox_message, integration_endpoint,"
                " human_decision, release_forecast, bottleneck_signal, ai_proposal,"
                " rtls_position, edge_batch, device_health, signal_reading, signal,"
                " visit_hold, discrepancy, order_link, dock_visit, move_deviation,"
                " move_task, spotter, escort, access_command, checklist_answer, checklist_item,"
                " checklist_template, identification_event, device,"
                " weighing_reprint, weighing_capture, axle_weight, tare_record,"
                " weighing_ticket, scale_reading, slot_reservation, appointment_change_log, appointment, priority_rule,"
                " plant_stoppage, shift_calendar, resource, visit_event, slot_occupancy, visit,"
                " slot, dock, zone, gate, scale, vehicle, driver, product, operation_type,"
                " carrier, plant CASCADE"
            )
        )
        await s.commit()
        yield s
    await engine.dispose()


@pytest.fixture
def ids():
    return {key: uuid.uuid4() for key in ("plant", "zone", "carrier", "operation")}


@pytest_asyncio.fixture
async def fixture_yard(session, ids):
    """Pátio mínimo: 1 planta, 1 zona, 2 vagas, 1 doca, 2 veículos, 2 motoristas."""
    await session.execute(
        insert(Plant),
        [{"id": ids["plant"], "code": "T-01", "name": "Teste", "timezone": "UTC"}],
    )
    await session.execute(
        insert(Carrier), [{"id": ids["carrier"], "code": "T-TRA", "name": "Teste Log"}]
    )
    await session.execute(
        insert(OperationType),
        [
            {
                "id": ids["operation"],
                "code": "RECEBIMENTO_GRANEL",
                "direction": "inbound",
                "requires_weighing": True,
                "requires_dock": True,
                "target_dwell_minutes": 90,
            }
        ],
    )
    await session.execute(
        insert(Zone),
        [{"id": ids["zone"], "plant_id": ids["plant"], "code": "Z-T", "kind": "parking"}],
    )
    slots = [
        {
            "id": uuid.uuid4(),
            "plant_id": ids["plant"],
            "zone_id": ids["zone"],
            "code": code,
            "kind": "parking",
            "status": status,
        }
        for code, status in (("T-01", "available"), ("T-02", "available"), ("T-99", "maintenance"))
    ]
    await session.execute(insert(Slot), slots)
    await session.execute(
        insert(Dock),
        [
            {
                "id": uuid.uuid4(),
                "plant_id": ids["plant"],
                "zone_id": ids["zone"],
                "code": code,
                "direction": "inbound",
                "status": "available",
            }
            for code in ("DOCK-T1", "DOCK-T2")
        ],
    )
    await session.execute(
        insert(Scale),
        [
            {
                "id": uuid.uuid4(),
                "plant_id": ids["plant"],
                "code": "SCALE-T1",
                "capacity_kg": 80000,
                "protocol": "simulator",
                "status": "online",
            }
        ],
    )
    await session.execute(
        insert(Gate),
        [
            {"id": uuid.uuid4(), "plant_id": ids["plant"], "code": "GATE-T1", "direction": "in"},
            {"id": uuid.uuid4(), "plant_id": ids["plant"], "code": "GATE-T2", "direction": "out"},
        ],
    )
    drivers = [
        {
            "id": uuid.uuid4(),
            "full_name": "Motorista Válido",
            "document": "10000000001",
            "license_expires_on": date.today() + timedelta(days=180),
            "carrier_id": ids["carrier"],
        },
        {
            "id": uuid.uuid4(),
            "full_name": "Motorista Vencido",
            "document": "10000000002",
            "license_expires_on": date.today() - timedelta(days=1),
            "carrier_id": ids["carrier"],
        },
    ]
    await session.execute(insert(Driver), drivers)
    vehicles = [
        {
            "id": uuid.uuid4(),
            "plate": plate,
            "kind": "truck",
            "carrier_id": ids["carrier"],
            "tare_kg": 12000,
        }
        for plate in ("TST1A01", "TST1A02", "TST1B01", "TST1B02", "TST9R00", "TST9R01")
    ]
    await session.execute(insert(Vehicle), vehicles)
    await session.commit()
    return {"slots": slots, "drivers": drivers, "vehicles": vehicles, **ids}


@pytest.fixture
def now():
    return datetime.now(timezone.utc)
