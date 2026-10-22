"""Seed rico: nenhuma tela do YARD nasce vazia.

Projeto demo único: uma planta de alimentos (fictícia) — recebimento de matéria-prima a
granel (farinha, açúcar, leite), insumos e embalagens paletizados, expedição de produto
acabado seco e refrigerado, com zona de cadeia fria e quarentena sanitária.

1 planta · 3 guaritas · 2 balanças · 24 docas · 180 vagas · ~400 movimentos/dia por 7 dias
mais um retrato do agora (veículos em triagem, em pátio e em doca).

    python -m app.seed            # popula (idempotente: limpa dados operacionais antes)
"""

import asyncio
import random
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import insert, text

from app.core.db import SessionLocal
import app.models  # noqa: F401  (registra o metadata completo)
from app.modules.catalog.models import Carrier, Driver, OperationType, Plant, Product, Vehicle
from app.modules.visits.models import Visit, VisitEvent
from app.modules.yard.models import Dock, Gate, Scale, Slot, SlotOccupancy, Zone

random.seed(42)

DAYS = 7
MOVES_PER_DAY = 400
VEHICLES = 140
DRIVERS = 180
CARRIERS = 10
SLOTS_PER_ZONE = 30

# Nomes inventados: demonstração não usa marca de ninguém.
CARRIER_NAMES = [
    "FrioSul Transportes", "Rota Láctea Log", "Granel Paulista", "Cadeia Fria Express",
    "Trigo & Cia Cargas", "Vale Verde Logística", "Paletiza Transportes", "Norte Frio",
    "Doce Rota Cargas", "Serra Azul Refrigerados",
]
FIRST = ["João", "Marcos", "Ana", "Carlos", "Paulo", "Rita", "Sérgio", "Luiz", "Fernanda", "Edson"]
LAST = ["Silva", "Souza", "Oliveira", "Pereira", "Costa", "Almeida", "Ramos", "Barbosa", "Lima"]
PRODUCTS = [
    ("MP-FAR-TRI", "Farinha de trigo a granel", False),
    ("MP-ACU-CRI", "Açúcar cristal a granel", False),
    ("MP-LEI-CRU", "Leite cru refrigerado (tanque)", False),
    ("MP-OLE-SOJ", "Óleo de soja refinado", False),
    ("MP-CAC-PO", "Cacau em pó 25kg", False),
    ("IN-EMB-FLX", "Embalagem flexível (bobinas)", False),
    ("IN-CX-PAP", "Caixas de papelão paletizadas", False),
    ("IN-CO2-ALI", "CO2 alimentício", True),
    ("IN-SAN-CIP", "Detergente CIP (sanitização)", True),
    ("PA-BIS-REC", "Biscoito recheado — palete", False),
    ("PA-IOG-REF", "Iogurte refrigerado — palete", False),
    ("PA-MAS-SEC", "Massa seca — palete", False),
]
OPERATIONS = [
    ("RECEBIMENTO_GRANEL", "inbound", True, True, 120),
    ("RECEBIMENTO_PALETIZADO", "inbound", False, True, 90),
    ("EXPEDICAO_GRANEL", "outbound", True, True, 150),
    ("EXPEDICAO_PALETIZADA", "outbound", False, True, 100),
    ("DEVOLUCAO", "inbound", False, True, 60),
    ("TRANSFERENCIA", "transit", True, False, 45),
]
# Geometria do pátio, em metros. Cada elemento tem faixa própria: balança dentro da
# zona e doca em cima da guarita é mapa que o operador lê errado.
# Z-A espera de recebimento · Z-B espera de expedição · Z-C pré-doca · Z-D cadeia fria
# (tomada para baú refrigerado) · Z-E fila de balança · Z-F quarentena sanitária.
ZONES = [
    ("Z-A", "parking", 0, 0, 290, 200, "--color-zone-a"),
    ("Z-B", "parking", 310, 0, 290, 200, "--color-zone-b"),
    ("Z-C", "staging", 620, 0, 290, 200, "--color-zone-c"),
    ("Z-D", "cold_chain", 0, 230, 290, 200, "--color-zone-d"),
    ("Z-E", "scale_queue", 310, 230, 290, 200, "--color-zone-e"),
    ("Z-F", "quarantine", 620, 230, 290, 200, "--color-zone-f"),
]

UTC = timezone.utc


def plate(i: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    a = letters[i % 26] + letters[(i // 26) % 26] + letters[(i // 7) % 26]
    return f"{a}{i % 10}{letters[(i // 3) % 26]}{(i // 11) % 10}{i % 10}"


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
        await session.execute(
            text(
                "TRUNCATE visit_event, slot_occupancy, visit, slot, dock, zone, gate, scale,"
                " vehicle, driver, product, operation_type, carrier, plant"
                " RESTART IDENTITY CASCADE"
            )
        )
        await session.execute(text("ALTER SEQUENCE visit_reference_seq RESTART WITH 1"))

        plant_id = uuid4()
        await session.execute(
            insert(Plant),
            [{"id": plant_id, "code": "PLANT-01", "name": "Planta Demo Alimentos",
              "timezone": "America/Sao_Paulo", "segment": "food", "city": "Campinas - SP",
              "description": "Projeto demonstração: biscoitos, massas e lácteos refrigerados."
              " Recebimento a granel com balança, expedição seca e refrigerada.",
              "active": True}],
        )

        carriers = [
            {"id": uuid4(), "code": f"TRA-{i + 1:03d}", "name": name,
             "tax_id": f"{10 + i:02d}.{i:03d}.{i:03d}/0001-{i:02d}", "active": True}
            for i, name in enumerate(CARRIER_NAMES[:CARRIERS])
        ]
        await session.execute(insert(Carrier), carriers)

        drivers = []
        for i in range(DRIVERS):
            expired = i % 40 == 7  # alguns com CNH vencida: a triagem precisa ter o que barrar
            drivers.append(
                {
                    "id": uuid4(),
                    "full_name": f"{random.choice(FIRST)} {random.choice(LAST)}",
                    "document": f"{100000000 + i * 137:011d}",
                    "license_number": f"{5000000000 + i}",
                    "license_expires_on": date.today()
                    + timedelta(days=-30 if expired else 200 + i % 400),
                    "phone": f"+5515{90000000 + i}",
                    "carrier_id": carriers[i % CARRIERS]["id"],
                    "active": True,
                }
            )
        await session.execute(insert(Driver), drivers)

        kinds = ["truck", "truck_trailer", "van", "container_chassis", "tanker"]
        vehicles = []
        for i in range(VEHICLES):
            tare = random.choice([7200, 9800, 12500, 14200, 16800])
            vehicles.append(
                {
                    "id": uuid4(),
                    "plate": plate(i),
                    "trailer_plate": plate(i + 500) if i % 3 == 0 else None,
                    "kind": kinds[i % len(kinds)],
                    "carrier_id": carriers[i % CARRIERS]["id"],
                    "axles": random.choice([3, 4, 5, 6, 9]),
                    "tare_kg": tare,
                    "max_gross_kg": tare + random.choice([20000, 30000, 40000]),
                    "active": True,
                }
            )
        await session.execute(insert(Vehicle), vehicles)

        products = [
            {"id": uuid4(), "sku": sku, "name": name, "hazardous": haz, "unit": "kg",
             "active": True}
            for sku, name, haz in PRODUCTS
        ]
        await session.execute(insert(Product), products)

        operations = [
            {"id": uuid4(), "code": code, "direction": direction, "requires_weighing": weigh,
             "requires_dock": dock, "target_dwell_minutes": dwell, "notes": None}
            for code, direction, weigh, dock, dwell in OPERATIONS
        ]
        await session.execute(insert(OperationType), operations)

        zones = [
            {"id": uuid4(), "plant_id": plant_id, "code": code, "kind": kind, "x": x, "y": y,
             "width": w, "height": h, "color_token": token}
            for code, kind, x, y, w, h, token in ZONES
        ]
        await session.execute(insert(Zone), zones)

        # Guaritas na borda oeste (entrada/saída) e uma ao sul, longe das docas.
        gates = [
            {"id": uuid4(), "plant_id": plant_id, "code": "GATE-01", "direction": "in",
             "x": -55, "y": 70, "active": True},
            {"id": uuid4(), "plant_id": plant_id, "code": "GATE-02", "direction": "out",
             "x": -55, "y": 300, "active": True},
            {"id": uuid4(), "plant_id": plant_id, "code": "GATE-03", "direction": "both",
             "x": 985, "y": 500, "active": True},
        ]
        await session.execute(insert(Gate), gates)

        # Balanças na faixa entre as zonas e as docas — é por onde o veículo passa.
        await session.execute(
            insert(Scale),
            [
                {"id": uuid4(), "plant_id": plant_id, "code": "SCALE-01", "capacity_kg": 80000,
                 "x": 950, "y": 110, "active": True},
                {"id": uuid4(), "plant_id": plant_id, "code": "SCALE-02", "capacity_kg": 100000,
                 "x": 950, "y": 300, "active": True},
            ],
        )

        # Docas em duas fileiras, ao leste, com corredor entre elas.
        docks = []
        for i in range(24):
            row, col = divmod(i, 12)
            docks.append(
                {
                    "id": uuid4(), "plant_id": plant_id, "zone_id": zones[2]["id"],
                    "code": f"DOCK-{i + 1:02d}",
                    "direction": "inbound" if i < 12 else "outbound",
                    "status": "blocked" if i == 17 else "available",
                    "x": 40 + col * 74, "y": 470 + row * 42,
                    "width": 66, "height": 34,
                }
            )
        await session.execute(insert(Dock), docks)

        slots = []
        for z_index, zone in enumerate(zones):
            letter = zone["code"].split("-")[1]
            for n in range(SLOTS_PER_ZONE):
                row, col = divmod(n, 6)
                slots.append(
                    {
                        "id": uuid4(), "plant_id": plant_id, "zone_id": zone["id"],
                        "code": f"{letter}-{n + 1:02d}",
                        "kind": zone["kind"] if zone["kind"] != "parking" else "parking",
                        "status": "maintenance" if (z_index == 5 and n > 27) else "available",
                        "length_m": 18,
                        # 6 vagas por fileira, 5 fileiras, com corredor entre elas.
                        # Vaga mais larga que alta: a placa cabe deitada e legível.
                        "x": float(zone["x"]) + 16 + col * 45,
                        "y": float(zone["y"]) + 30 + row * 33,
                        "width": 38, "height": 24, "notes": None,
                    }
                )
        await session.execute(insert(Slot), slots)
        usable_slots = [s for s in slots if s["status"] == "available"]

        # ---------------- histórico operacional ----------------
        visits: list[dict] = []
        occupancies: list[dict] = []
        events: list[dict] = []
        reference_seq = 0
        today = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

        def new_event(visit_id: UUID, at: datetime, kind: str, frm, to, source, payload):
            events.append(
                {"id": uuid4(), "occurred_at": at, "visit_id": visit_id, "event_type": kind,
                 "source": source, "actor": "seed", "from_state": frm, "to_state": to,
                 "payload": payload}
            )

        slot_cursor = 0
        for day in range(DAYS, 0, -1):
            day_start = (today - timedelta(days=day)).replace(hour=9)  # 06:00 local
            per_vehicle = MOVES_PER_DAY // VEHICLES + 1
            day_moves = []
            for v_index, vehicle in enumerate(vehicles):
                for k in range(per_vehicle):
                    if len(day_moves) >= MOVES_PER_DAY:
                        break
                    offset = timedelta(minutes=k * 210 + (v_index % 20) * 7)
                    day_moves.append((vehicle, day_start + offset))
            day_moves.sort(key=lambda m: m[1])

            for vehicle, arrived in day_moves:
                reference_seq += 1
                operation = random.choice(operations)
                dwell = timedelta(minutes=random.randint(35, operation["target_dwell_minutes"] + 60))
                gate_in_at = arrived + timedelta(minutes=random.randint(3, 22))
                dock = random.choice(docks)
                dock_in = gate_in_at + timedelta(minutes=random.randint(5, 40))
                dock_out = dock_in + timedelta(minutes=random.randint(20, 90))
                gate_out_at = arrived + dwell
                if gate_out_at <= dock_out:
                    gate_out_at = dock_out + timedelta(minutes=10)
                visit_id = uuid4()
                driver = drivers[(reference_seq * 3) % DRIVERS]
                visits.append(
                    {
                        "id": visit_id, "plant_id": plant_id,
                        "reference": f"YRD-{arrived.year}-{reference_seq:06d}",
                        "state": "departed", "vehicle_id": vehicle["id"],
                        "driver_id": driver["id"], "carrier_id": vehicle["carrier_id"],
                        "product_id": random.choice(products)["id"],
                        "operation_type_id": operation["id"],
                        "gate_in_id": gates[0]["id"], "gate_out_id": gates[1]["id"],
                        "current_slot_id": None, "current_dock_id": None,
                        "arrived_at": arrived, "gate_in_at": gate_in_at,
                        "dock_in_at": dock_in, "dock_out_at": dock_out,
                        "gate_out_at": gate_out_at,
                        "seal_number": f"LAC{random.randint(100000, 999999)}",
                        "document_number": f"NFE{random.randint(100000, 999999)}",
                        "notes": None, "blocked_reason_code": None,
                    }
                )
                slot = usable_slots[slot_cursor % len(usable_slots)]
                slot_cursor += 1
                occupancies.append(
                    {"id": uuid4(), "slot_id": slot["id"], "visit_id": visit_id,
                     "vehicle_id": vehicle["id"], "started_at": gate_in_at, "ended_at": dock_in}
                )
                new_event(visit_id, arrived, "gate_in", None, "at_gate_in",
                          random.choice(["manual", "device", "device"]), {"plate": vehicle["plate"]})
                new_event(visit_id, gate_in_at, "slot_assigned", "at_gate_in", "in_yard",
                          "system", {"slot": slot["code"]})
                new_event(visit_id, dock_in, "dock_assigned", "in_yard", "at_dock",
                          "manual", {"dock": dock["code"]})
                new_event(visit_id, gate_out_at, "gate_out", "at_gate_out", "departed",
                          "device", {"dwell_seconds": int((gate_out_at - arrived).total_seconds())})

        # ---------------- retrato do agora ----------------
        now = datetime.now(UTC)
        live_vehicles = random.sample(vehicles, 46)
        live_slots = usable_slots[:60]
        for i, vehicle in enumerate(live_vehicles):
            reference_seq += 1
            operation = random.choice(operations)
            visit_id = uuid4()
            driver = drivers[(i * 5) % DRIVERS]
            arrived = now - timedelta(minutes=random.randint(5, 260))
            if i < 8:
                state, gate_in_at, dock_in, dock = "at_gate_in", None, None, None
            elif i < 38:
                state = "in_yard"
                gate_in_at = arrived + timedelta(minutes=random.randint(4, 18))
                dock_in, dock = None, None
            else:
                state = "at_dock"
                gate_in_at = arrived + timedelta(minutes=random.randint(4, 18))
                dock_in = gate_in_at + timedelta(minutes=random.randint(10, 60))
                dock = docks[i - 38]
            slot = live_slots[i] if state == "in_yard" else None
            visits.append(
                {
                    "id": visit_id, "plant_id": plant_id,
                    "reference": f"YRD-{now.year}-{reference_seq:06d}", "state": state,
                    "vehicle_id": vehicle["id"], "driver_id": driver["id"],
                    "carrier_id": vehicle["carrier_id"],
                    "product_id": random.choice(products)["id"],
                    "operation_type_id": operation["id"], "gate_in_id": gates[0]["id"],
                    "gate_out_id": None,
                    "current_slot_id": slot["id"] if slot else None,
                    "current_dock_id": dock["id"] if dock else None,
                    "arrived_at": arrived, "gate_in_at": gate_in_at, "dock_in_at": dock_in,
                    "dock_out_at": None, "gate_out_at": None,
                    "seal_number": f"LAC{random.randint(100000, 999999)}",
                    "document_number": f"NFE{random.randint(100000, 999999)}",
                    "notes": None,
                    # uma pendência aberta para a tela ter o que bloquear
                    "blocked_reason_code": "PENDING_FISCAL_DOC" if i == 12 else None,
                }
            )
            new_event(visit_id, arrived, "gate_in", None, "at_gate_in", "device",
                      {"plate": vehicle["plate"]})
            if slot:
                occupancies.append(
                    {"id": uuid4(), "slot_id": slot["id"], "visit_id": visit_id,
                     "vehicle_id": vehicle["id"], "started_at": gate_in_at, "ended_at": None}
                )
                new_event(visit_id, gate_in_at, "slot_assigned", "at_gate_in", "in_yard",
                          "system", {"slot": slot["code"]})
            if dock:
                new_event(visit_id, dock_in, "dock_assigned", "in_yard", "at_dock", "manual",
                          {"dock": dock["code"]})
                await session.execute(
                    text("UPDATE dock SET status='occupied' WHERE id=:id"), {"id": dock["id"]}
                )

        await session.execute(insert(Visit), visits)
        await session.execute(insert(SlotOccupancy), occupancies)
        for chunk in range(0, len(events), 2000):
            await session.execute(insert(VisitEvent), events[chunk:chunk + 2000])
        await session.execute(
            text("SELECT setval('visit_reference_seq', :v)"), {"v": reference_seq}
        )
        await session.commit()

        print(
            f"seed: {len(visits)} visitas, {len(occupancies)} ocupações, {len(events)} eventos, "
            f"{len(slots)} vagas, {len(docks)} docas, {len(vehicles)} veículos"
        )


if __name__ == "__main__":
    asyncio.run(main())
