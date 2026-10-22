"""Seed da Fatia 2: recursos, turnos, regras de prioridade e agenda de 3 dias.

    python -m app.seed_scheduling      # roda depois de `python -m app.seed`
"""

import asyncio
import random
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

from sqlalchemy import insert, select, text

from app.core.db import SessionLocal
import app.models  # noqa: F401  (registra o metadata completo)
from app.modules.catalog.models import OperationType, Plant, Product, Vehicle
from app.modules.scheduling.models import (
    Appointment,
    AppointmentChangeLog,
    PriorityRule,
    Resource,
    ShiftCalendar,
    SlotReservation,
)
from app.modules.yard.models import Dock, Slot

random.seed(7)
UTC = timezone.utc

RESOURCES = [
    ("EMP-01", "forklift", 3), ("EMP-02", "forklift", 3), ("MOE-01", "hopper", 1),
    ("MOE-02", "hopper", 1), ("EQP-A", "labor_crew", 2), ("EQP-B", "labor_crew", 2),
    ("PONTE-01", "crane", 1), ("BOMBA-01", "pump", 1),
]

# Prioridade é dado: mexer na ordem é UPDATE, não deploy.
PRIORITY_RULES = [
    ("PERISHABLE", 1, {"perishable": True}),
    ("CROSS_DOCK", 2, {"operation_type": "TRANSFERENCIA"}),
    ("PRODUCTION_FIRM", 3, {"operation_type": "RECEBIMENTO_GRANEL"}),
    ("HAZMAT_WINDOW", 4, {"hazardous": True}),
    ("DEDICATED_FLEET", 5, {"channel": "internal"}),
    ("PORTAL_STANDARD", 9, {"channel": "portal"}),
]


def _refuse_in_production() -> None:
    """Seed é ferramenta de desenvolvimento e demonstração.

    Rodar isto contra a base da planta apagaria operação real (os seeds truncam) e
    encheria o histórico de dado inventado — que depois vira KPI, relatório e decisão.
    """
    from app.core.config import settings

    if settings.is_production:
        raise SystemExit(
            "seed recusado: YARD_ENV=prod. Popular base de produção com dado "
            "sintético corrompe o histórico e os indicadores da planta."
        )


async def main() -> None:
    _refuse_in_production()
    async with SessionLocal() as session:
        # DELETE, não TRUNCATE CASCADE: `visit.appointment_id` referencia `appointment`,
        # e um TRUNCATE CASCADE aqui levaria o pátio inteiro junto.
        await session.execute(text("UPDATE visit SET appointment_id = NULL"))
        for table in (
            "slot_reservation",
            "appointment_change_log",
            "appointment",
            "priority_rule",
            "plant_stoppage",
            "shift_calendar",
            "resource",
        ):
            await session.execute(text(f"DELETE FROM {table}"))
        await session.execute(text("ALTER SEQUENCE appointment_reference_seq RESTART WITH 1"))

        plant = (await session.execute(select(Plant))).scalars().first()
        docks = (await session.execute(select(Dock).order_by(Dock.code))).scalars().all()
        slots = (
            await session.execute(select(Slot).where(Slot.status == "available").order_by(Slot.code))
        ).scalars().all()
        vehicles = (await session.execute(select(Vehicle).order_by(Vehicle.plate))).scalars().all()
        operations = (await session.execute(select(OperationType))).scalars().all()
        products = (await session.execute(select(Product))).scalars().all()

        resources = [
            {"id": uuid4(), "plant_id": plant.id, "code": code, "kind": kind, "capacity": capacity}
            for code, kind, capacity in RESOURCES
        ]
        await session.execute(insert(Resource), resources)

        # Turno: 06:00–22:00 de segunda a sábado (horário local ≈ UTC-3).
        shifts = [
            {
                "id": uuid4(), "plant_id": plant.id, "code": f"T1-{weekday}",
                "weekday": weekday, "starts_time": time(9, 0), "ends_time": time(23, 59),
            }
            for weekday in range(0, 6)
        ]
        await session.execute(insert(ShiftCalendar), shifts)

        await session.execute(
            insert(PriorityRule),
            [
                {"id": uuid4(), "code": code, "rank": rank, "match_json": match, "active": True}
                for code, rank, match in PRIORITY_RULES
            ],
        )

        # Agenda: 3 dias, janelas de 90min por doca, ~55% de ocupação.
        appointments: list[dict] = []
        reservations: list[dict] = []
        logs: list[dict] = []
        reference = 0
        base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        used_vehicle_windows: dict[str, list[tuple[datetime, datetime]]] = {}
        slot_cursor = 0

        for day in range(3):
            for dock_index, dock in enumerate(docks):
                for window in range(6):
                    if random.random() > 0.55:
                        continue
                    starts = base + timedelta(days=day, minutes=window * 100 + dock_index * 7)
                    ends = starts + timedelta(minutes=90)
                    vehicle = random.choice(vehicles)
                    windows = used_vehicle_windows.setdefault(str(vehicle.id), [])
                    if any(s < ends and e > starts for s, e in windows):
                        continue
                    windows.append((starts, ends))
                    reference += 1
                    operation = random.choice(operations)
                    product = random.choice(products)
                    state = random.choice(
                        ["confirmed", "confirmed", "confirmed", "requested", "cancelled"]
                    )
                    appointment_id = uuid4()
                    channel = random.choice(["internal", "portal", "portal"])
                    rule = next(
                        (r for r in PRIORITY_RULES if r[2].get("channel") == channel), None
                    )
                    appointments.append(
                        {
                            "id": appointment_id, "plant_id": plant.id,
                            "reference": f"APT-{starts.year}-{reference:06d}",
                            "state": state, "dock_id": dock.id, "vehicle_id": vehicle.id,
                            "driver_id": None, "carrier_id": vehicle.carrier_id,
                            "product_id": product.id, "operation_type_id": operation.id,
                            "resource_id": random.choice(resources)["id"],
                            "visit_id": None, "slot_id": None,
                            "starts_at": starts, "ends_at": ends,
                            "priority_code": rule[0] if rule else None,
                            "priority_rank": rule[1] if rule else 999,
                            "created_by": "seed", "channel": channel, "version": 1,
                        }
                    )
                    logs.append(
                        {
                            "id": uuid4(), "appointment_id": appointment_id,
                            "occurred_at": starts - timedelta(hours=random.randint(4, 48)),
                            "actor": "seed",
                            # CHECK ck_change_log_reason: cancelar sem motivo não existe
                            "reason_code": "CARRIER_REQUEST" if state == "cancelled" else None,
                            "from_state": None,
                            "to_state": state, "from_starts_at": None, "to_starts_at": starts,
                            "impact_json": {},
                        }
                    )
                    if state == "confirmed" and slots:
                        slot = slots[slot_cursor % len(slots)]
                        slot_cursor += 1
                        appointments[-1]["slot_id"] = slot.id
                        reservations.append(
                            {
                                "id": uuid4(), "slot_id": slot.id,
                                "appointment_id": appointment_id, "vehicle_id": vehicle.id,
                                "state": "active",
                                "starts_at": starts - timedelta(minutes=30), "ends_at": ends,
                            }
                        )

        await session.execute(insert(Appointment), appointments)
        if reservations:
            await session.execute(insert(SlotReservation), reservations)
        await session.execute(insert(AppointmentChangeLog), logs)
        await session.execute(
            text("SELECT setval('appointment_reference_seq', :v)"), {"v": max(reference, 1)}
        )
        await session.commit()
        print(
            f"seed agendamento: {len(appointments)} janelas, {len(reservations)} reservas de vaga,"
            f" {len(resources)} recursos, {len(PRIORITY_RULES)} regras de prioridade"
        )


if __name__ == "__main__":
    asyncio.run(main())
