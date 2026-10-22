"""Seed da Fatia 4: dispositivos de campo, checklists e histórico de identificação.

    python -m app.seed_gate      # roda depois de `python -m app.seed`
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import insert, select, text

import app.models  # noqa: F401  (registra o metadata completo)
from app.core.db import SessionLocal
from app.modules.catalog.models import OperationType, Plant
from app.modules.gate.models import (
    ChecklistItem,
    ChecklistTemplate,
    Device,
    IdentificationEvent,
)
from app.modules.iot.models import DeviceHealth, Signal, SignalReading
from app.modules.moves.models import Spotter
from app.modules.visits.models import Visit
from app.modules.yard.models import Dock, Gate, Scale

random.seed(11)
UTC = timezone.utc

# Item é código estável; o texto vive no i18n da tela.
BASE_ITEMS = [
    ("EPI_COMPLETE", "blocking", False),
    ("FIRE_EXTINGUISHER", "blocking", False),
    ("CARGO_SECURED", "blocking", True),
    ("SEAL_INTACT", "blocking", True),
    ("TIRE_CONDITION", "warning", False),
    ("DRIVER_BRIEFING", "info", False),
]
HAZMAT_ITEMS = [
    ("HAZMAT_PLACARD", "blocking", True),
    ("HAZMAT_KIT", "blocking", False),
    ("LEAK_INSPECTION", "blocking", True),
    ("HAZMAT_DOCUMENTATION", "blocking", False),
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
        # TRUNCATE, não DELETE: `identification_event` e `access_command` são append-only
        # por trigger — e é exatamente isso que o seed não pode contornar linha a linha.
        # As tabelas vão juntas num comando só para as FKs entre elas não atrapalharem.
        await session.execute(
            text(
                "TRUNCATE rtls_position, edge_batch, device_health, signal_reading, signal,"
                " escort, access_command, checklist_answer, checklist_item,"
                " checklist_template, identification_event, device"
            )
        )

        plant = (await session.execute(select(Plant))).scalars().first()
        gates = (await session.execute(select(Gate).order_by(Gate.code))).scalars().all()
        docks = (await session.execute(select(Dock).order_by(Dock.code))).scalars().all()
        scales = (await session.execute(select(Scale).order_by(Scale.code))).scalars().all()
        operations = (await session.execute(select(OperationType))).scalars().all()

        devices: list[dict] = []

        def add(code: str, kind: str, **refs):
            devices.append(
                {
                    "id": uuid4(), "plant_id": plant.id, "code": code, "kind": kind,
                    "protocol": "simulator", "status": "online",
                    "last_seen_at": datetime.now(UTC),
                    "gate_id": refs.get("gate"), "dock_id": refs.get("dock"),
                    "scale_id": refs.get("scale"),
                }
            )

        for gate in gates:
            add(f"BAR-{gate.code[-2:]}", "barrier", gate=gate.id)
            add(f"SEM-{gate.code[-2:]}", "traffic_light", gate=gate.id)
            add(f"LPR-{gate.code[-2:]}", "lpr_camera", gate=gate.id)
            add(f"LOOP-{gate.code[-2:]}", "loop_detector", gate=gate.id)
            add(f"RFID-{gate.code[-2:]}", "rfid_reader", gate=gate.id)
            add(f"KIOSK-{gate.code[-2:]}", "kiosk", gate=gate.id)
        for scale in scales:
            add(f"IND-{scale.code[-2:]}", "scale_indicator", scale=scale.id)
            add(f"PHC-{scale.code[-2:]}", "photocell", scale=scale.id)
        for dock in docks[:6]:
            add(f"SEM-{dock.code}", "traffic_light", dock=dock.id)
        add("PLC-MAIN", "plc")
        # Um dispositivo em manutenção: a tela de saúde precisa ter o que mostrar.
        devices[3]["status"] = "maintenance"
        devices[10]["status"] = "degraded"
        await session.execute(insert(Device), devices)

        # Manobristas: a fila de manobra é por pessoa, e pessoa precisa existir.
        await session.execute(text("DELETE FROM spotter"))
        await session.execute(
            insert(Spotter),
            [
                {"id": uuid4(), "plant_id": plant.id, "code": f"MAN-{i:02d}",
                 "full_name": name, "shift_code": "T1" if i <= 3 else "T2", "active": True}
                for i, name in enumerate(
                    ["Adriano Peixoto", "Beatriz Nunes", "Cleber Matos",
                     "Diego Rangel", "Elaine Castro", "Fábio Teixeira"], start=1
                )
            ],
        )

        base_template = uuid4()
        hazmat_template = uuid4()
        await session.execute(
            insert(ChecklistTemplate),
            [
                {"id": base_template, "code": "GATE_IN_BASE", "direction": "in",
                 "operation_type_id": None, "hazardous_only": False, "active": True},
                {"id": hazmat_template, "code": "GATE_IN_HAZMAT", "direction": "in",
                 "operation_type_id": None, "hazardous_only": True, "active": True},
                {"id": uuid4(), "code": "GATE_OUT_BASE", "direction": "out",
                 "operation_type_id": operations[0].id if operations else None,
                 "hazardous_only": False, "active": True},
            ],
        )
        await session.execute(
            insert(ChecklistItem),
            [
                {"id": uuid4(), "template_id": base_template, "code": code, "position": i + 1,
                 "severity": severity, "requires_photo": photo}
                for i, (code, severity, photo) in enumerate(BASE_ITEMS)
            ]
            + [
                {"id": uuid4(), "template_id": hazmat_template, "code": code, "position": i + 1,
                 "severity": severity, "requires_photo": photo}
                for i, (code, severity, photo) in enumerate(HAZMAT_ITEMS)
            ],
        )

        # Histórico de identificação: 88% automático, 12% digitado — para o KPI ter chão.
        visits = (
            await session.execute(select(Visit).order_by(Visit.arrived_at.desc()).limit(400))
        ).scalars().all()
        events = []
        for visit in visits:
            automatic = random.random() < 0.88
            method = random.choice(["lpr", "lpr", "qr", "rfid"]) if automatic else "manual"
            confidence = round(random.uniform(0.86, 0.99), 3) if method == "lpr" else None
            events.append(
                {
                    "id": uuid4(),
                    "occurred_at": visit.arrived_at + timedelta(seconds=random.randint(2, 45)),
                    "gate_id": gates[0].id,
                    "device_id": devices[2]["id"],
                    "method": method,
                    "raw_value": visit.reference,
                    "normalized_value": visit.reference,
                    "confidence": confidence,
                    "matched_vehicle_id": visit.vehicle_id,
                    "matched_appointment_id": None,
                    "visit_id": visit.id,
                    "state": "matched" if automatic else "manual_override",
                    "image_ref": f"s3://yard/lpr/{visit.reference}.jpg" if method == "lpr" else None,
                    "actor": None if automatic else "guarda.01",
                }
            )
        await session.execute(insert(IdentificationEvent), events)

        # Sinais de campo: permissivo por cancela, estado por semáforo, medida por moega.
        # É o que dá conteúdo ao simulador IoT e à tela de saúde de dispositivo.
        signals: list[dict] = []
        readings: list[dict] = []
        health: list[dict] = []
        for device in devices:
            kind_map = {
                "barrier": [("PERMISSIVE", "permissive", "bool", True),
                            ("POSITION", "status", "bool", False)],
                "traffic_light": [("STATE", "status", "string", False)],
                "loop_detector": [("OCCUPIED", "status", "bool", False)],
                "photocell": [("BLOCKED", "status", "bool", False)],
                "plc": [("SAFETY_OK", "permissive", "bool", True)],
                "hopper_level": [("LEVEL", "measure", "float", False)],
                "scale_indicator": [("WEIGHT", "measure", "float", False)],
            }
            for code, kind, data_type, safety in kind_map.get(device["kind"], []):
                signal_id = uuid4()
                signals.append(
                    {
                        "id": signal_id, "device_id": device["id"], "code": code,
                        "path": f"plant-01/{device['kind']}/{device['code']}/{code.lower()}",
                        "kind": kind, "data_type": data_type, "unit": None,
                        "safety_related": safety, "stale_after_seconds": 30,
                        "source_address": f"ns=2;s={device['code']}.{code}",
                    }
                )
                readings.append(
                    {
                        "id": uuid4(),
                        "occurred_at": datetime.now(UTC) - timedelta(seconds=random.randint(1, 8)),
                        "received_at": datetime.now(UTC),
                        "signal_id": signal_id, "device_id": device["id"],
                        "value_bool": True if data_type == "bool" else None,
                        "value_num": round(random.uniform(10, 90), 2)
                        if data_type == "float" else None,
                        "value_text": "green" if data_type == "string" else None,
                        "quality": "good", "sequence_number": 1, "batch_id": None,
                    }
                )
            health.append(
                {
                    "id": uuid4(), "occurred_at": datetime.now(UTC),
                    "device_id": device["id"], "status": device["status"],
                    "latency_ms": random.randint(5, 60), "error_code": None, "detail": None,
                }
            )
        await session.execute(insert(Signal), signals)
        await session.execute(insert(SignalReading), readings)
        await session.execute(insert(DeviceHealth), health)
        await session.commit()
        print(
            f"seed portaria: {len(devices)} dispositivos, "
            f"{len(BASE_ITEMS) + len(HAZMAT_ITEMS)} itens de checklist, "
            f"{len(events)} identificações, {len(signals)} sinais, 6 manobristas"
        )


if __name__ == "__main__":
    asyncio.run(main())
