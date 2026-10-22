"""Laço de campo: liga os conectores ao banco e à saúde dos dispositivos.

Sobe junto com a API quando `YARD_FIELD_MODE=live`. Cada leitura que chega é gravada com
a hora do campo e a qualidade que o campo declarou; cada silêncio vira `no_comm` por
tempo, não por palpite.
"""

import asyncio
import contextlib
import logging
from datetime import timedelta

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.events import hub
from app.modules.iot import service
from app.modules.iot.field import FieldConnector, build_connectors
from app.modules.iot.schemas import ReadingIn

log = logging.getLogger("yard.field.runtime")

# Sem notícia por 3× o limite de frescor do sinal, o dispositivo é dado como offline.
WATCHDOG_INTERVAL = 15


class FieldRuntime:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._connectors: list[FieldConnector] = []

    async def start(self) -> None:
        self._connectors = build_connectors()
        if not self._connectors:
            log.info("campo em modo %s: nenhum conector ativo", settings.field_mode)
            return
        for connector in self._connectors:
            log.info("iniciando conector de campo: %s", connector.name)
            self._tasks.append(asyncio.create_task(connector.start(self._on_reading)))
        self._tasks.append(asyncio.create_task(self._watchdog()))

    async def _on_reading(self, path: str, payload: dict) -> None:
        """Uma leitura de campo. Nada de lógica aqui além de persistir com qualidade."""
        value = payload.get("value")
        reading = ReadingIn(
            path=path,
            occurred_at=payload["occurred_at"],
            quality=payload.get("quality", "good"),
            sequence_number=payload.get("sequence_number"),
            value_bool=value if isinstance(value, bool) else None,
            value_num=value if isinstance(value, (int, float)) and not isinstance(value, bool)
            else None,
            value_text=value if isinstance(value, str) else None,
        )
        async with SessionLocal() as session:
            await service.ingest(session, [reading])

    async def _watchdog(self) -> None:
        """Dispositivo que parou de falar é dispositivo offline — e a torre precisa ver.

        Sem isso, a última leitura boa fica na tela para sempre, com cara de atual.
        """
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            try:
                async with SessionLocal() as session:
                    silent = (
                        await session.execute(
                            text(
                                """
                                SELECT d.code
                                  FROM device d
                                  JOIN signal s ON s.device_id = d.id
                                  LEFT JOIN LATERAL (
                                      SELECT max(occurred_at) AS last_at
                                        FROM signal_reading r
                                       WHERE r.signal_id = s.id
                                  ) last ON true
                                 WHERE d.status = 'online'
                                 GROUP BY d.code
                                HAVING coalesce(max(last.last_at), 'epoch'::timestamptz)
                                       < now() - make_interval(secs => max(
                                           s.stale_after_seconds) * 3)
                                """
                            )
                        )
                    ).scalars().all()
                    for code in silent:
                        await service.record_health(
                            session, code, "offline", error_code="WATCHDOG_TIMEOUT"
                        )
                        log.warning("dispositivo %s sem leitura: marcado offline", code)
                    if silent:
                        await hub.publish("yard.device.watchdog", {"devices": list(silent)})
            except Exception as exc:  # noqa: BLE001 - watchdog não pode morrer
                log.error("watchdog de campo falhou: %s", exc)

    async def command(self, device_code: str, signal_code: str, value: object) -> bool:
        """Escreve no campo pelo primeiro conector que aceitar."""
        for connector in self._connectors:
            with contextlib.suppress(Exception):
                if await connector.command(device_code, signal_code, value):
                    return True
        return False

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for connector in self._connectors:
            await connector.stop()
        self._tasks.clear()


runtime = FieldRuntime()


def stale_threshold(seconds: int) -> timedelta:
    return timedelta(seconds=seconds * 3)
