"""Drivers de indicador de balança.

Uma interface, vários protocolos: o serviço nunca sabe se o peso veio de uma Toledo por
RS-232, de um indicador por TCP ou do simulador. Trocar de balança é trocar o driver.

Protocolo de indicador é texto cru e sujo — cada fabricante com seu quadro. O parser fica
aqui, isolado, e o resto do sistema só vê `ScaleSample`.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ScaleSample:
    weight_kg: int
    stable: bool
    occurred_at: datetime
    quality: str = "good"  # good | stale | invalid | no_comm
    raw: str = ""


class ScaleDriver:
    """Contrato mínimo. `read()` devolve a leitura corrente do indicador."""

    protocol = "abstract"

    async def read(self) -> ScaleSample:  # pragma: no cover - interface
        raise NotImplementedError

    async def close(self) -> None:
        return None


# Toledo 9091 / MGR: <STX> peso(6) <ETX>, com bit de estabilidade no status.
TOLEDO_FRAME = re.compile(r"\x02(?P<status>[A-Z])?(?P<weight>-?\d{1,7})(?:\.(?P<dec>\d+))?\x03")
GENERIC_FRAME = re.compile(r"(?P<sign>[+-]?)\s*(?P<weight>\d{1,7})(?:[.,](?P<dec>\d+))?\s*kg?",
                           re.IGNORECASE)


def parse_frame(raw: str, protocol: str) -> ScaleSample:
    """Traduz o quadro do indicador. Quadro ilegível vira qualidade `invalid`, não zero."""
    now = datetime.now(timezone.utc)
    pattern = TOLEDO_FRAME if "toledo" in protocol else GENERIC_FRAME
    match = pattern.search(raw)
    if not match:
        return ScaleSample(weight_kg=0, stable=False, occurred_at=now, quality="invalid", raw=raw)

    weight = int(match.group("weight"))
    if match.groupdict().get("sign") == "-":
        weight = -weight
    stable = True
    if "toledo" in protocol:
        # status 'I' = instável (in motion), 'S' = estável
        stable = (match.group("status") or "S").upper() != "I"
    return ScaleSample(
        weight_kg=max(0, weight), stable=stable, occurred_at=now, quality="good", raw=raw
    )


class TcpScaleDriver(ScaleDriver):
    """Indicador em rede: `host:porta`, quadro por linha."""

    protocol = "tcp_generic"

    def __init__(self, endpoint: str, protocol: str = "tcp_generic") -> None:
        self.host, _, port = endpoint.partition(":")
        self.port = int(port or 4001)
        self.protocol = protocol
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def _ensure(self) -> None:
        if self._reader is None:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=3
            )

    async def read(self) -> ScaleSample:
        try:
            await self._ensure()
            assert self._reader is not None
            raw = await asyncio.wait_for(self._reader.readline(), timeout=2)
            return parse_frame(raw.decode("ascii", errors="ignore"), self.protocol)
        except (TimeoutError, OSError, AssertionError):
            # Sem comunicação é estado explícito, não peso zero — número sem frescor mente.
            self._reader = self._writer = None
            return ScaleSample(
                weight_kg=0,
                stable=False,
                occurred_at=datetime.now(timezone.utc),
                quality="no_comm",
            )

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._reader = self._writer = None


class SerialScaleDriver(ScaleDriver):
    """RS-232. `pyserial` é opcional: sem ele, o driver reporta `no_comm` e o pátio segue."""

    protocol = "serial_generic"

    def __init__(self, endpoint: str, protocol: str = "serial_toledo", baudrate: int = 9600):
        self.endpoint = endpoint
        self.protocol = protocol
        self.baudrate = baudrate
        self._port = None

    async def read(self) -> ScaleSample:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError:
            return ScaleSample(
                weight_kg=0,
                stable=False,
                occurred_at=datetime.now(timezone.utc),
                quality="no_comm",
                raw="pyserial ausente",
            )
        if self._port is None:
            self._port = serial.Serial(self.endpoint, self.baudrate, timeout=1)
        raw = await asyncio.to_thread(self._port.readline)
        return parse_frame(raw.decode("ascii", errors="ignore"), self.protocol)


class SimulatorScaleDriver(ScaleDriver):
    """Balança falsa: sobe o peso, oscila, estabiliza. Sem hardware, o sistema inteiro roda.

    Reproduz o que atrapalha de verdade em campo: peso instável, veículo mal posicionado
    e leitura fora de faixa.
    """

    protocol = "simulator"

    def __init__(self, target_kg: int = 42000, noise_kg: int = 60) -> None:
        self.target = target_kg
        self.noise = noise_kg
        self._current = 0
        self._history: deque[int] = deque(maxlen=6)
        self._ticks = 0

    def set_target(self, target_kg: int) -> None:
        self.target = target_kg
        self._current = 0
        self._ticks = 0
        self._history.clear()

    async def read(self) -> ScaleSample:
        self._ticks += 1
        # sobe rápido e depois assenta, como caminhão entrando na plataforma
        gap = self.target - self._current
        self._current += int(gap * 0.8) + random.randint(-self.noise, self.noise)
        self._history.append(self._current)
        # Estável = assentou perto do alvo e parou de balançar, nas últimas 3 leituras.
        window = list(self._history)[-3:]
        spread = max(window) - min(window) if len(window) == 3 else 99_999
        stable = (
            self._ticks >= 4
            and abs(self._current - self.target) <= self.noise * 2
            and spread <= self.noise * 3
        )
        return ScaleSample(
            weight_kg=max(0, self._current),
            stable=stable,
            occurred_at=datetime.now(timezone.utc),
            quality="good",
            raw=f"\x02{'S' if stable else 'I'}{max(0, self._current):06d}\x03",
        )


_REGISTRY: dict[str, ScaleDriver] = {}


def driver_for(scale_code: str, protocol: str, endpoint: str | None) -> ScaleDriver:
    """Um driver por balança, reaproveitado entre requisições."""
    if scale_code in _REGISTRY:
        return _REGISTRY[scale_code]
    if protocol.startswith("tcp") and endpoint:
        driver: ScaleDriver = TcpScaleDriver(endpoint, protocol)
    elif protocol.startswith("serial") and endpoint:
        driver = SerialScaleDriver(endpoint, protocol)
    else:
        driver = SimulatorScaleDriver()
    _REGISTRY[scale_code] = driver
    return driver
