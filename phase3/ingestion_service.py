"""MQTT telemetry ingestion service for Phase 3.

The service validates every room message, adds a UTC reception timestamp,
prints structured JSON records, and optionally appends them to a JSONL file.
It deliberately does not use a database; persistence belongs to Phase 4.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from phase3.telemetry_core import (
    TELEMETRY_TOPIC,
    TelemetryValidationError,
    build_ingestion_record,
)


BROKER_HOST = os.getenv("MQTT_BROKER", "broker.hivemq.com")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
SUBSCRIBE_TOPIC = os.getenv("MQTT_TELEMETRY_TOPIC", TELEMETRY_TOPIC)
LOG_PATH = os.getenv("TELEMETRY_LOG_PATH", "").strip()


def emit(record: dict[str, Any]) -> None:
    line = json.dumps(record, separators=(",", ":"), allow_nan=False)
    print(line, flush=True)
    if LOG_PATH:
        path = Path(LOG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def main() -> int:
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("Missing dependency: install with 'pip install -r requirements-phase3.txt'", file=sys.stderr)
        return 2

    def on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code == 0:
            client.subscribe(SUBSCRIBE_TOPIC, qos=1)
            emit({"event": "mqtt_connected", "topic": SUBSCRIBE_TOPIC})
        else:
            emit({"event": "mqtt_connection_failed", "reason_code": str(reason_code)})

    def on_disconnect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        emit({"event": "mqtt_disconnected", "reason_code": str(reason_code)})

    def on_message(client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            emit(build_ingestion_record(message.topic, message.payload))
        except TelemetryValidationError as exc:
            emit({"event": "telemetry_rejected", "topic": message.topic, "reason": str(exc)})

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"energy-ingestion-{os.getpid()}",
        protocol=mqtt.MQTTv311,
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    emit({"event": "service_starting", "broker": BROKER_HOST, "port": BROKER_PORT})
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        emit({"event": "service_stopped"})
        client.disconnect()
        return 0
    except OSError as exc:
        emit({"event": "service_error", "reason": str(exc)})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
