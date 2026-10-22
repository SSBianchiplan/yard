#!/usr/bin/env python
"""Ponta a ponta pela API: um caminhão do agendamento à saída.

Percorre o caminho completo de uma visita real, chamando os mesmos endpoints que as
telas chamam — cadastro, agendamento, portaria, checklist, cancela, pátio, manobra,
doca, balança e saída — e mostra, em cada passo, qual regra foi aplicada.

    python scripts/e2e_demo.py --api http://127.0.0.1:8088 \
        --plate AAA3251 --driver "Stéfano Motorista"

Não é substituto do pytest (lá ficam os invariantes): aqui o objetivo é provar que o
sistema inteiro conversa e produzir um roteiro de demonstração reproduzível.
"""

from __future__ import annotations

import argparse
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

UTC = timezone.utc
step_number = 0
failures: list[str] = []


def step(title: str) -> None:
    global step_number
    step_number += 1
    print(f"\n\033[1m{step_number:2d}. {title}\033[0m")


def ok(message: str) -> None:
    print(f"    ✓ {message}")


def bad(message: str) -> None:
    failures.append(message)
    print(f"    ✗ {message}")


def note(message: str) -> None:
    print(f"      {message}")


def show_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error", {})
        return f"{error.get('code', response.status_code)} {error.get('params', '')}"
    except Exception:  # noqa: BLE001
        return f"HTTP {response.status_code}"


def ascii_document(name: str) -> str:
    """CPF fictício estável derivado do nome — o mesmo nome gera o mesmo documento."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    digits = sum(ord(char) for char in normalized)
    return f"{90000000000 + digits % 9999999:011d}"


class Demo:
    def __init__(self, base: str, plate: str, driver_name: str) -> None:
        self.base = base.rstrip("/")
        self.api = f"{self.base}/api/v1"
        self.plate = plate.upper()
        self.driver_name = driver_name
        self.driver_document = ascii_document(driver_name)
        self.client = httpx.Client(timeout=20)
        self.state: dict[str, Any] = {}

    # ------------------------------------------------------------------ helpers
    def get(self, path: str, **params: Any) -> Any:
        response = self.client.get(f"{self.api}{path}", params=params or None)
        response.raise_for_status()
        return response.json()

    def post(
        self, path: str, payload: dict | None = None, query: dict | None = None
    ) -> httpx.Response:
        return self.client.post(f"{self.api}{path}", json=payload or {}, params=query)

    def simulate_scale(self, scale_code: str, target_kg: int) -> None:
        """Coloca a balança simulada no peso alvo — em campo, é o caminhão subindo."""
        self.post(f"/weighing/scales/{scale_code}/simulate", query={"target_kg": target_kg})

    def tick_field(self) -> None:
        """Um ciclo de leitura do campo: sem isso o permissivo envelhece e nada abre."""
        self.post("/iot/simulate")

    # ------------------------------------------------------------------ passos
    def preparar(self) -> None:
        """Deixa o pátio pronto para repetir a demonstração com a mesma placa.

        Sem isso, a segunda execução esbarra nas próprias regras do sistema — visita
        aberta, janela ocupada — e o roteiro vira um teste de "já rodou antes".
        """
        step("Preparar: encerrar o que ficou de execuções anteriores")

        open_visits = [
            visit
            for visit in self.get("/visits", only_open=True, search=self.plate)
            if visit["plate"] == self.plate
        ]
        for visit in open_visits:
            for hold in self.get(f"/docks/visits/{visit['id']}/holds"):
                if hold["released_at"] is None:
                    self.post(
                        f"/docks/holds/{hold['id']}/release",
                        {"released_by": "demo.reset"},
                    )
            if visit["state"] == "at_gate_in":
                # Quem ainda está na guarita não "sai": é recusado na triagem.
                result = self.post(
                    f"/visits/{visit['id']}/reject",
                    {"reason_code": "DEMO_RESET", "actor": "demo.reset"},
                )
                verb = "recusada na triagem"
            else:
                result = self.post(
                    f"/visits/{visit['id']}/gate-out", {"gate_code": "GATE-02"}
                )
                verb = "encerrada"
            if result.status_code == 200:
                ok(f"visita anterior {visit['reference']} {verb}")
            else:
                note(f"visita {visit['reference']} não encerrou: {show_error(result)}")

        for appointment in self.get("/scheduling/appointments", limit=500):
            if appointment["plate"] != self.plate:
                continue
            if appointment["state"] in ("confirmed", "requested", "checked_in"):
                self.post(
                    f"/scheduling/appointments/{appointment['id']}/cancel",
                    {"reason_code": "DEMO_RESET", "version": appointment["version"]},
                )
                ok(f"janela anterior {appointment['reference']} cancelada")

        for task in self.get("/moves/queue"):
            if task["plate"] == self.plate:
                result = self.post(
                    f"/moves/tasks/{task['id']}/cancel",
                    {"reason_code": "DEMO_RESET", "actor": "demo.reset"},
                )
                if result.status_code == 200:
                    ok(f"tarefa de manobra {task['reference']} cancelada")

        if not open_visits:
            ok("nada pendente da última execução")

    def cadastro(self) -> None:
        step("Cadastro: transportadora, motorista e veículo")
        carriers = self.get("/catalog/carriers", limit=1)
        carrier_id = carriers[0]["id"]
        note(f"transportadora: {carriers[0]['name']}")

        existing = self.get("/catalog/drivers", search=self.driver_name)
        if existing:
            driver = existing[0]
            ok(f"motorista já cadastrado: {driver['full_name']} ({driver['document']})")
        else:
            response = self.post(
                "/catalog/drivers",
                {
                    "full_name": self.driver_name,
                    "document": self.driver_document,
                    "license_number": "99887766554",
                    # CNH válida: vencida barraria o gate-in (ASSUNCOES #3)
                    "license_expires_on": (datetime.now(UTC) + timedelta(days=420)).date().isoformat(),
                    "phone": "+5515998887766",
                    "carrier_id": carrier_id,
                    "active": True,
                },
            )
            if response.status_code != 201:
                bad(f"cadastro do motorista recusado: {show_error(response)}")
                return
            driver = response.json()
            ok(f"motorista criado: {driver['full_name']} · CPF {driver['document']}")
        self.state["driver"] = driver

        existing = self.get("/catalog/vehicles", search=self.plate)
        if existing:
            vehicle = existing[0]
            ok(f"veículo já cadastrado: {vehicle['plate']}")
        else:
            response = self.post(
                "/catalog/vehicles",
                {
                    "plate": self.plate,
                    "trailer_plate": None,
                    "kind": "truck_trailer",
                    "carrier_id": carrier_id,
                    "axles": 6,
                    "tare_kg": 15200,
                    "max_gross_kg": 48000,
                    "active": True,
                },
            )
            if response.status_code != 201:
                bad(f"cadastro do veículo recusado: {show_error(response)}")
                return
            vehicle = response.json()
            ok(f"veículo criado: {vehicle['plate']} · tara cadastral {vehicle['tare_kg']} kg")
        self.state["vehicle"] = vehicle

    def agendamento(self) -> None:
        step("Agendamento: janela de doca com capacidade finita")
        docks = self.get("/yard/docks")
        free_dock = next((d for d in docks if d["status"] == "available"), docks[0])
        starts = (datetime.now(UTC) + timedelta(minutes=20)).replace(second=0, microsecond=0)
        ends = starts + timedelta(minutes=90)

        response = self.post(
            "/scheduling/appointments",
            {
                "dock_code": free_dock["code"],
                "plate": self.plate,
                "operation_type_code": "RECEBIMENTO_GRANEL",
                "driver_document": self.state["driver"]["document"],
                "starts_at": starts.isoformat(),
                "ends_at": ends.isoformat(),
                "actor": "demo.e2e",
            },
        )
        if response.status_code != 201:
            bad(f"agendamento recusado: {show_error(response)}")
            return
        appointment = response.json()
        self.state["appointment"] = appointment
        ok(f"janela {appointment['reference']} em {free_dock['code']} · estado {appointment['state']}")
        note(f"prioridade aplicada por regra: {appointment['priority_code']}")

        response = self.post(
            f"/scheduling/appointments/{appointment['id']}/confirm",
            {"version": appointment["version"], "actor": "demo.e2e"},
        )
        if response.status_code != 200:
            bad(f"confirmação recusada: {show_error(response)}")
            return
        confirmed = response.json()
        self.state["appointment"] = confirmed
        ok(f"confirmado · vaga reservada: {confirmed['slot_code']}")

        # Concorrência otimista: a mesma versão não serve duas vezes.
        conflict = self.post(
            f"/scheduling/appointments/{confirmed['id']}/reschedule",
            {
                "starts_at": (starts + timedelta(hours=3)).isoformat(),
                "ends_at": (ends + timedelta(hours=3)).isoformat(),
                "reason_code": "DEMO",
                "version": appointment["version"],  # versão velha de propósito
            },
        )
        if conflict.status_code == 409:
            ok(f"versão velha recusada: {show_error(conflict)}")
        else:
            bad("reprogramação com versão velha deveria ter sido recusada")

    def portaria(self) -> None:
        step("Portaria: identificação, triagem e gate-in")
        appointment = self.state["appointment"]

        low = self.post(
            "/gate/identify",
            {
                "gate_code": "GATE-01",
                "method": "lpr",
                "value": self.plate,
                "confidence": 0.61,
                "image_ref": f"s3://yard/lpr/{self.plate}.jpg",
            },
        )
        if low.status_code == 409:
            ok(f"LPR com baixa confiança não libera: {show_error(low)}")
        else:
            bad("LPR abaixo do limiar deveria cair para conferência humana")

        good = self.post(
            "/gate/identify",
            {"gate_code": "GATE-01", "method": "qr", "value": appointment["reference"]},
        )
        if good.status_code != 200:
            bad(f"identificação por QR falhou: {show_error(good)}")
            return
        decision = good.json()
        ok(f"QR do agendamento reconhecido · triagem: {decision['decision']}")

        response = self.post(
            "/visits/gate-in",
            {
                "plate": self.plate,
                "driver_document": self.state["driver"]["document"],
                "operation_type_code": "RECEBIMENTO_GRANEL",
                "gate_code": "GATE-01",
                "appointment_reference": appointment["reference"],
                "document_number": "NFE900123456",
                "seal_number": "LAC778899",
                "source": "device",
                "actor": "demo.e2e",
            },
        )
        if response.status_code != 201:
            bad(f"gate-in recusado: {show_error(response)}")
            return
        visit = response.json()
        self.state["visit"] = visit
        ok(f"entrada registrada: {visit['reference']} · estado {visit['state']}")

    def checklist(self) -> None:
        step("Checklist de entrada: item bloqueante segura o veículo")
        visit = self.state["visit"]
        items = self.get(f"/gate/visits/{visit['id']}/checklist")
        note(f"{len(items)} itens exigidos para esta operação")

        blocking = next(item for item in items if item["severity"] == "blocking")
        failed = self.post(
            f"/gate/visits/{visit['id']}/checklist",
            {
                "actor": "guarda.demo",
                "answers": [
                    {
                        "item_id": blocking["id"],
                        "passed": False,
                        "photo_ref": "s3://yard/checklist/falha.jpg",
                        "note": "conferência da demonstração",
                    }
                ],
            },
        )
        if failed.status_code == 200 and failed.json():
            ok(f"reprovado em {failed.json()[0]} — visita bloqueada")
        else:
            bad("item bloqueante reprovado deveria bloquear a visita")

        denied = self.post(f"/visits/{visit['id']}/slot", {"actor": "demo.e2e"})
        if denied.status_code == 409:
            ok(f"liberação para o pátio recusada: {show_error(denied)}")
        else:
            bad("checklist reprovado deveria impedir a liberação")

        # Reinspeção: o guarda confere de novo e aprova todos os itens.
        passed = self.post(
            f"/gate/visits/{visit['id']}/checklist",
            {
                "actor": "guarda.demo",
                "answers": [{"item_id": item["id"], "passed": True} for item in items],
            },
        )
        if passed.status_code != 200:
            bad(f"reinspeção falhou: {show_error(passed)}")
            return
        ok("reinspeção aprovada em todos os itens")
        # A pendência aberta pelo trigger precisa ser liberada por outra pessoa.
        holds = self.get(f"/docks/visits/{visit['id']}/holds")
        for hold in holds:
            if hold["released_at"] is None:
                release = self.post(
                    f"/docks/holds/{hold['id']}/release", {"released_by": "supervisor.demo"}
                )
                if release.status_code == 200:
                    ok(f"pendência {hold['reason_code']} liberada por supervisor.demo")
                else:
                    bad(f"liberação da pendência falhou: {show_error(release)}")

    def cancela(self) -> None:
        step("Cancela: comando físico com permissivo do CLP")
        visit = self.state["visit"]
        devices = self.get("/gate/devices", kind="barrier")
        barrier = next((d for d in devices if d["status"] == "online"), None)
        if barrier is None:
            bad("nenhuma cancela online")
            return

        # Permissivo tem prazo de validade: leitura velha não abre cancela (§3.8).
        self.tick_field()
        permissive = self.get(f"/iot/devices/{barrier['code']}/permissive")
        note(f"permissivo lido do campo: {permissive['permissive']} ({permissive['quality']})")

        denied_ai = self.post(
            "/gate/command",
            {
                "device_code": barrier["code"],
                "action": "open_barrier",
                "origin": "ai",
                "authorized_by": "torre.demo",
            },
        )
        if denied_ai.status_code == 409:
            ok(f"comando de IA sem aprovação recusado: {show_error(denied_ai)}")
        else:
            bad("comando de IA sem aprovação humana deveria ser recusado")

        for _ in range(6):
            command = self.post(
                "/gate/command",
                {
                    "device_code": barrier["code"],
                    "action": "open_barrier",
                    "visit_id": visit["id"],
                    "origin": "human",
                    "authorized_by": "guarda.demo",
                },
            )
            if command.status_code == 200:
                ok(f"cancela {barrier['code']}: {command.json()['state']}")
                break
            if command.status_code == 409:
                note(f"tentativa negada pelo CLP ({show_error(command)}) — repetindo")
                self.tick_field()
            time.sleep(0.4)
        else:
            bad("cancela não abriu em nenhuma tentativa")

    def patio(self) -> None:
        step("Pátio: alocação de vaga (reserva do agendamento é respeitada)")
        visit = self.state["visit"]
        response = self.post(f"/visits/{visit['id']}/slot", {"actor": "demo.e2e"})
        if response.status_code != 200:
            bad(f"alocação recusada: {show_error(response)}")
            return
        visit = response.json()
        self.state["visit"] = visit
        reserved = self.state["appointment"]["slot_code"]
        if visit["slot_code"] == reserved:
            ok(f"vaga {visit['slot_code']} — a mesma reservada na confirmação")
        else:
            ok(f"vaga {visit['slot_code']} (reserva era {reserved})")

    def manobra(self) -> None:
        step("Manobra: fila por custo e confirmação por leitura de QR")
        visit = self.state["visit"]
        slots = self.get("/yard/slots")
        target = next(
            s for s in slots if not s["occupied"] and s["status"] == "available"
        )

        response = self.post(
            "/moves/tasks",
            {
                "visit_reference": visit["reference"],
                "to_slot_code": target["code"],
                "priority_rank": 100,
                "sla_minutes": 30,
            },
        )
        if response.status_code != 201:
            bad(f"tarefa de manobra recusada: {show_error(response)}")
            return
        task = response.json()
        ok(f"tarefa {task['reference']} · custo {task['cost_score']} · {task['distance_m']} m")

        spotters = self.get("/moves/spotters")
        spotter = spotters[0]["code"]
        self.post(f"/moves/tasks/{task['id']}/accept", {"spotter_code": spotter})
        self.post(f"/moves/tasks/{task['id']}/start")
        ok(f"aceita por {spotter} e iniciada")

        wrong = self.post(
            f"/moves/tasks/{task['id']}/confirm", {"kind": "qr", "value": "VAGA-ERRADA"}
        )
        if wrong.status_code == 409:
            ok(f"QR de vaga errada vira desvio: {show_error(wrong)}")
        else:
            bad("QR divergente deveria gerar desvio")

        confirmed = self.post(
            f"/moves/tasks/{task['id']}/confirm", {"kind": "qr", "value": target["code"]}
        )
        if confirmed.status_code == 200:
            ok(f"confirmada por leitura na vaga {target['code']}")
            self.state["visit"] = self.get(f"/visits/{visit['id']}")
        else:
            bad(f"confirmação recusada: {show_error(confirmed)}")

    def doca(self) -> None:
        step("Doca: cronometria por etapa e vínculo com a ordem")
        visit = self.state["visit"]
        dock_code = self.state["appointment"]["dock_code"]

        response = self.post(f"/visits/{visit['id']}/dock", {"dock_code": dock_code})
        if response.status_code != 200:
            bad(f"encosto em doca recusado: {show_error(response)}")
            return
        ok(f"encostado em {dock_code}")

        self.post(f"/docks/visits/{visit['id']}/orders",
                  {"kind": "purchase_order", "external_id": "OC-778899", "quantity": 30000,
                   "unit": "kg"})
        ok("vinculado à ordem de compra OC-778899")

        for stage, reason in (("arrived", None), ("docked", None), ("started", None),
                              ("pause", "NO_FORKLIFT"), ("resume", None), ("finished", None),
                              ("released", None)):
            payload: dict[str, Any] = {"stage": stage}
            if stage == "arrived":
                payload["dock_code"] = dock_code
            if reason:
                payload["reason_code"] = reason
            result = self.post(f"/docks/visits/{visit['id']}/stage", payload)
            if result.status_code != 200:
                bad(f"etapa {stage} recusada: {show_error(result)}")
                return
        ok("etapas cronometradas: chegada → encosto → início → pausa → retomada → fim → liberação")

    def balanca(self) -> None:
        step("Balança: bruto, tara, líquido e conferência com a NF-e")
        visit = self.state["visit"]
        scales = self.get("/yard/map")["scales"]
        scale_code = scales[0]["code"]

        response = self.post(
            "/weighing/tickets",
            {
                "visit_reference": visit["reference"],
                "scale_code": scale_code,
                "document_number": "NFE900123456",
                "document_net_kg": 30000,
                "tolerance_pct": 0.5,
                "operator": "balanca.demo",
                # Reentrada da mesma placa na mesma balança em menos de 10 min é
                # tratada como suspeita; repetir a demonstração é o caso legítimo,
                # e o caminho previsto é justificar — não é contornar a regra.
                "reentry_justified": True,
            },
        )
        if response.status_code != 201:
            bad(f"abertura de ticket recusada: {show_error(response)}")
            return
        ticket = response.json()
        ok(f"ticket {ticket['reference']} aberto na {scale_code}")

        # Caminhão sobe na balança (no campo real, é o caminhão mesmo).
        self.simulate_scale(scale_code, 45300)
        unstable = self.post(
            f"/weighing/tickets/{ticket['id']}/capture",
            {"kind": "gross", "vehicle_positioned": False, "image_ref": "s3://g.jpg"},
        )
        if unstable.status_code == 409:
            ok(f"veículo mal posicionado não pesa: {show_error(unstable)}")
        else:
            bad("captura com veículo fora de posição deveria ser recusada")

        gross = self.post(
            f"/weighing/tickets/{ticket['id']}/capture",
            {"kind": "gross", "image_ref": "s3://yard/weighing/gross.jpg"},
        )
        if gross.status_code != 200:
            bad(f"captura do bruto falhou: {show_error(gross)}")
            return
        ok(f"bruto capturado: {gross.json()['gross_kg']} kg")

        self.simulate_scale(scale_code, 15250)
        tare = self.post(
            f"/weighing/tickets/{ticket['id']}/capture",
            {"kind": "tare", "image_ref": "s3://yard/weighing/tare.jpg"},
        )
        if tare.status_code != 200:
            bad(f"captura da tara falhou: {show_error(tare)}")
            return
        ok(f"tara aferida: {tare.json()['tare_kg']} kg (cadastral era 15200)")

        closed = self.post(f"/weighing/tickets/{ticket['id']}/close", {})
        if closed.status_code != 200:
            bad(f"fechamento recusado: {show_error(closed)}")
            return
        data = closed.json()
        ok(
            f"líquido {data['net_kg']} kg · divergência {data['divergence_pct']}% "
            f"· dentro da tolerância: {data['within_tolerance']}"
        )
        note(f"hash de integridade: {data['integrity_hash'][:24]}…")
        self.state["ticket"] = data

        frozen = self.post(f"/weighing/tickets/{ticket['id']}/close", {})
        if frozen.status_code == 409:
            ok(f"ticket fechado é imutável: {show_error(frozen)}")
        else:
            bad("ticket fechado deveria recusar alteração")

    def saida(self) -> None:
        step("Saída: bloqueio por pendência e liberação final")
        visit = self.state["visit"]

        hold = self.post(
            f"/docks/visits/{visit['id']}/holds",
            {
                "kind": "fiscal",
                "reason_code": "AWAITING_NFE_VALIDATION",
                "opened_by": "fiscal.demo",
            },
        )
        if hold.status_code != 201:
            bad(f"abertura de pendência falhou: {show_error(hold)}")
            return
        ok("pendência fiscal aberta por fiscal.demo")

        blocked = self.post(f"/visits/{visit['id']}/gate-out", {"gate_code": "GATE-02"})
        if blocked.status_code == 409:
            ok(f"saída bloqueada: {show_error(blocked)}")
        else:
            bad("saída com pendência aberta deveria ser bloqueada")

        same_person = self.post(
            f"/docks/holds/{hold.json()['id']}/release", {"released_by": "fiscal.demo"}
        )
        if same_person.status_code == 409:
            ok(f"quem abriu não libera: {show_error(same_person)}")
        else:
            bad("segregação de função deveria impedir a autoliberação")

        release = self.post(
            f"/docks/holds/{hold.json()['id']}/release", {"released_by": "supervisor.demo"}
        )
        if release.status_code != 200:
            bad(f"liberação recusada: {show_error(release)}")
            return
        ok("pendência liberada por supervisor.demo")

        out = self.post(f"/visits/{visit['id']}/gate-out", {"gate_code": "GATE-02"})
        if out.status_code != 200:
            bad(f"saída recusada: {show_error(out)}")
            return
        final = out.json()
        ok(f"saída registrada · dwell total {final['dwell_seconds'] // 60} min")
        self.state["visit"] = final

    def trilha(self) -> None:
        step("Trilha e integrações: o que ficou registrado")
        visit = self.get(f"/visits/{self.state['visit']['id']}")
        print(f"      {len(visit['events'])} eventos na trilha da visita:")
        for event in reversed(visit["events"]):
            print(
                f"        {event['occurred_at'][11:19]}  {event['event_type']:<16}"
                f" {event['source']:<10} {event['from_state'] or '—'} → {event['to_state'] or '—'}"
            )

        outbox = self.get("/integrations/outbox", limit=200)
        mine = [m for m in outbox if m["aggregate_id"] == visit["id"]]
        ok(f"{len(mine)} mensagens no outbox para esta visita (ERP/WMS/BI)")

        tickets = self.get("/weighing/tickets", visit_reference=visit["reference"])
        ok(f"{len(tickets)} ticket(s) de pesagem vinculado(s)")

        snapshot = self.get("/integrations/bi/kpi-snapshot")
        note(
            f"KPI agora: gate-in hoje {int(snapshot['gate_in_today'])}, "
            f"eventos automáticos {snapshot['automatic_event_pct']:.1f}%"
        )

    def run(self) -> int:
        print(f"\033[1mYARD — demonstração ponta a ponta\033[0m")
        print(f"placa {self.plate} · motorista {self.driver_name} · API {self.base}")
        health = self.client.get(f"{self.base}/health").json()
        # fora de dev o /health só diz "ok" (não expõe modo de auth nem ambiente)
        print(
            f"ambiente {health.get('env', '?')} · campo {health.get('field_mode', '?')}"
            f" · auth {health.get('auth_mode', '?')}"
        )

        required = {
            "agendamento": "driver",
            "portaria": "appointment",
            "checklist": "visit",
            "cancela": "visit",
            "patio": "visit",
            "manobra": "visit",
            "doca": "visit",
            "balanca": "visit",
            "saida": "visit",
            "trilha": "visit",
        }

        for phase in (
            self.preparar,
            self.cadastro,
            self.agendamento,
            self.portaria,
            self.checklist,
            self.cancela,
            self.patio,
            self.manobra,
            self.doca,
            self.balanca,
            self.saida,
            self.trilha,
        ):
            dependency = required.get(phase.__name__)
            if dependency and dependency not in self.state:
                note(f"{phase.__name__}: pulado (faltou {dependency} do passo anterior)")
                continue
            try:
                phase()
            except Exception as exc:  # noqa: BLE001
                bad(f"{phase.__name__} quebrou: {type(exc).__name__}: {exc}")

        print()
        if failures:
            print(f"\033[1m✗ {len(failures)} passo(s) com problema:\033[0m")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print(f"\033[1m✓ fluxo completo: {step_number} etapas, nenhuma regra violada.\033[0m")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--plate", default="AAA3251")
    parser.add_argument("--driver", default="Stéfano Motorista")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    return Demo(args.api, args.plate, args.driver).run()


if __name__ == "__main__":
    raise SystemExit(main())
