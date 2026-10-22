"""Campo real: MQTT Sparkplug B e OPC UA.

Este módulo é o que troca o simulador por hardware. O resto do sistema não muda de uma
linha: continua lendo `signal_current` e mandando comando por `access_command`.

Duas escolhas que valem explicar:

**Sparkplug B, não MQTT cru.** O que importa não é o tópico, é o ciclo de vida: NBIRTH/
DBIRTH descrevem as tags, NDEATH/DDEATH (via Last Will) avisam que o nó caiu. Sem isso,
um edge que morre silencia — e silêncio vira "valor antigo parece atual", que é
exatamente o que a camada de qualidade existe para impedir.

**Qualidade vem do campo, não do relógio do servidor.** OPC UA entrega StatusCode junto
do valor; Sparkplug entrega `is_null` e o estado do nó. Os dois viram `good | stale |
invalid | no_comm` na mesma tabela.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

log = logging.getLogger("yard.field")

# Assinatura do que o conector entrega para a aplicação.
OnReading = Callable[[str, dict[str, Any]], "asyncio.Future[None] | None"]


def now() -> datetime:
    return datetime.now(timezone.utc)


class FieldConnector:
    """Contrato comum. `start()` conecta e fica ouvindo; `command()` escreve no campo."""

    name = "abstract"

    async def start(self, on_reading: OnReading) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def command(
        self, device_code: str, signal_code: str, value: Any
    ) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    async def stop(self) -> None:
        return None


class SparkplugConnector(FieldConnector):
    """MQTT Sparkplug B.

    Tópicos: `spBv1.0/<group>/<msg>/<node>[/<device>]`. Assinamos as mensagens de dados e
    de nascimento/morte; cada métrica vira um caminho no modelo de informação único.
    """

    name = "mqtt_sparkplug"

    def __init__(self) -> None:
        self._client = None
        self._task: asyncio.Task | None = None
        self._alive: dict[str, bool] = {}

    def _path(self, node: str, device: str | None, metric: str) -> str:
        parts = [settings.plant_code.lower(), node.lower()]
        if device:
            parts.append(device.lower())
        parts.append(metric.lower().replace("/", "_"))
        return "/".join(parts)

    async def start(self, on_reading: OnReading) -> None:
        try:
            from asyncio_mqtt import Client, MqttError  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - dependência opcional
            raise RuntimeError(
                "modo live exige o extra de campo: pip install -e '.[field]'"
            ) from exc

        topic = f"spBv1.0/{settings.mqtt_group_id}/#"
        backoff = 1
        while True:
            try:
                async with Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_username,
                    password=settings.mqtt_password,
                    tls_context=_tls_context() if settings.mqtt_tls else None,
                    client_id=f"yard-{settings.mqtt_node_id}",
                ) as client:
                    self._client = client
                    backoff = 1
                    log.info("sparkplug conectado em %s", settings.mqtt_host)
                    async with client.messages() as messages:
                        await client.subscribe(topic, qos=1)
                        async for message in messages:
                            await self._handle(str(message.topic), message.payload, on_reading)
            except MqttError as exc:
                # Rede de planta cai. O edge continua bufferizando e reconciliando depois;
                # aqui a única obrigação é voltar e não inundar o log.
                log.warning("sparkplug caiu (%s); religando em %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)

    async def _handle(self, topic: str, payload: bytes, on_reading: OnReading) -> None:
        parts = topic.split("/")
        if len(parts) < 4:
            return
        _, _group, message_type, node, *rest = parts
        device = rest[0] if rest else None

        if message_type in ("NDEATH", "DDEATH"):
            # Morte do nó: tudo que ele publica passa a valer como sem comunicação.
            self._alive[node] = False
            await _maybe_await(on_reading(self._path(node, device, "__node_state__"),
                                          {"quality": "no_comm", "occurred_at": now()}))
            return
        if message_type in ("NBIRTH", "DBIRTH"):
            self._alive[node] = True

        try:
            body = _decode_sparkplug(payload)
        except Exception:  # noqa: BLE001 - payload de campo chega torto mesmo
            log.debug("payload sparkplug ilegível em %s", topic)
            return

        for metric in body.get("metrics", []):
            name = metric.get("name")
            if not name:
                continue
            quality = "invalid" if metric.get("is_null") else "good"
            if not self._alive.get(node, True):
                quality = "no_comm"
            await _maybe_await(
                on_reading(
                    self._path(node, device, name),
                    {
                        "value": metric.get("value"),
                        "quality": quality,
                        # A hora é a do campo. Sempre.
                        "occurred_at": _epoch_to_dt(metric.get("timestamp")) or now(),
                        "sequence_number": body.get("seq"),
                    },
                )
            )

    async def command(self, device_code: str, signal_code: str, value: Any) -> bool:
        """Escrita via NCMD/DCMD — o CLP continua com a última palavra sobre executar."""
        if self._client is None:
            return False
        topic = (
            f"spBv1.0/{settings.mqtt_group_id}/DCMD/{settings.mqtt_node_id}/{device_code}"
        )
        payload = json.dumps(
            {
                "timestamp": int(now().timestamp() * 1000),
                "metrics": [{"name": signal_code, "value": value}],
            }
        ).encode()
        await self._client.publish(topic, payload, qos=1)
        return True

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


class OpcUaConnector(FieldConnector):
    """OPC UA por assinatura. StatusCode do servidor vira qualidade, sem tradução criativa."""

    name = "opcua"

    def __init__(self) -> None:
        self._client = None

    async def start(self, on_reading: OnReading) -> None:
        try:
            from asyncua import Client, ua  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - dependência opcional
            raise RuntimeError(
                "modo live exige o extra de campo: pip install -e '.[field]'"
            ) from exc

        backoff = 1
        while True:
            try:
                client = Client(url=settings.opcua_endpoint)
                if settings.opcua_username:
                    client.set_user(settings.opcua_username)
                    client.set_password(settings.opcua_password or "")
                async with client:
                    self._client = client
                    backoff = 1
                    log.info("opc ua conectado em %s", settings.opcua_endpoint)

                    handler = _OpcSubscriptionHandler(on_reading)
                    subscription = await client.create_subscription(500, handler)
                    nodes = await _nodes_to_watch(client)
                    if nodes:
                        await subscription.subscribe_data_change(nodes)
                    while True:
                        await asyncio.sleep(5)
                        await client.check_connection()
            except (OSError, asyncio.TimeoutError, ua.UaError) as exc:
                log.warning("opc ua caiu (%s); religando em %ss", exc, backoff)
                self._client = None
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)

    async def command(self, device_code: str, signal_code: str, value: Any) -> bool:
        if self._client is None:
            return False
        node = self._client.get_node(f"ns=2;s={device_code}.{signal_code}")
        await node.write_value(value)
        return True


class _OpcSubscriptionHandler:
    def __init__(self, on_reading: OnReading) -> None:
        self._on_reading = on_reading

    def datachange_notification(self, node, value, data) -> None:  # noqa: ANN001
        status = data.monitored_item.Value.StatusCode
        quality = "good" if status.is_good() else "invalid"
        source_time = data.monitored_item.Value.SourceTimestamp
        payload = {
            "value": value,
            "quality": quality,
            "occurred_at": source_time or now(),
        }
        result = self._on_reading(str(node), payload)
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)


async def _nodes_to_watch(client) -> list:  # noqa: ANN001
    """Nós assinados = `source_address` dos sinais cadastrados.

    O mapeamento vive no banco (tabela `signal`), não no código: trocar o endereço de uma
    tag é UPDATE, não deploy.
    """
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.modules.iot.models import Signal

    async with SessionLocal() as session:
        addresses = (
            await session.execute(
                select(Signal.source_address).where(Signal.source_address.is_not(None))
            )
        ).scalars().all()
    return [client.get_node(address) for address in addresses]


def _tls_context():
    import ssl

    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _decode_sparkplug(payload: bytes) -> dict[str, Any]:
    """Aceita protobuf quando a lib está presente; cai para JSON quando o edge publica JSON.

    Muita planta roda gateway que publica Sparkplug "em JSON" — funciona, e recusar isso
    só serviria para o pátio ficar sem dado.
    """
    try:
        from sparkplug_b import sparkplug_b_pb2  # type: ignore[import-not-found]

        message = sparkplug_b_pb2.Payload()
        message.ParseFromString(payload)
        return {
            "seq": message.seq,
            "metrics": [
                {
                    "name": metric.name,
                    "value": _sparkplug_value(metric),
                    "timestamp": metric.timestamp,
                    "is_null": metric.is_null,
                }
                for metric in message.metrics
            ],
        }
    except ImportError:
        return json.loads(payload.decode("utf-8"))


def _sparkplug_value(metric) -> Any:  # noqa: ANN001
    for attribute in ("boolean_value", "int_value", "long_value", "float_value",
                      "double_value", "string_value"):
        if metric.HasField(attribute):
            return getattr(metric, attribute)
    return None


def _epoch_to_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


async def _maybe_await(result) -> None:  # noqa: ANN001
    if asyncio.iscoroutine(result):
        await result


def build_connectors() -> list[FieldConnector]:
    """Conectores ativos conforme a configuração. Em `simulator`, nenhum."""
    if settings.field_mode != "live":
        return []
    connectors: list[FieldConnector] = []
    if settings.mqtt_host:
        connectors.append(SparkplugConnector())
    if settings.opcua_endpoint:
        connectors.append(OpcUaConnector())
    return connectors
