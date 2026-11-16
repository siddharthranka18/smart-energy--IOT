"""Background MQTT subscription for the existing room telemetry topic."""

from __future__ import annotations

import logging
import os
import threading
from time import monotonic
from typing import Any
from uuid import uuid4

from phase4.config import Settings
from phase4.control import LOADS, on_ack, on_sample, publish_command, publish_off, record_failure
from phase4.ingest import ingest_message


logger = logging.getLogger("phase4")
DEMO_VISIBLE_SECONDS = 12


class ServiceStatus:
    """Small status board shared by the MQTT thread and the health endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.mqtt_connected = False
        self.last_mqtt_error: str | None = None
        self.stored_count = 0
        self.rejected_count = 0
        self.duplicate_count = 0
        self.database_error_count = 0

    def set_mqtt_connected(self, connected: bool, error: str | None = None) -> None:
        with self._lock:
            self.mqtt_connected = connected
            self.last_mqtt_error = error

    def record(self, status: str) -> None:
        with self._lock:
            if status == "stored":
                self.stored_count += 1
            elif status == "rejected":
                self.rejected_count += 1
            elif status == "duplicate":
                self.duplicate_count += 1
            elif status == "database_error":
                self.database_error_count += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mqtt_connected": self.mqtt_connected,
                "last_mqtt_error": self.last_mqtt_error,
                "stored_count": self.stored_count,
                "rejected_count": self.rejected_count,
                "duplicate_count": self.duplicate_count,
                "database_error_count": self.database_error_count,
            }


class TelemetryListener:
    """Subscribe to telemetry and hand each payload to ingest_message."""

    def __init__(self, settings: Settings, session_factory: Any, status: ServiceStatus) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.status = status
        self._client: Any = None
        self._demo_lock = threading.Lock()
        self._room_demos: dict[str, tuple[str, float, bool]] = {}

    def start_equipment_demo(self, topic: str, target: str) -> str:
        with self._demo_lock:
            if self._client is None or not self._client.is_connected():
                return "offline"
            now = monotonic()
            self._room_demos = {key: demo for key, demo in self._room_demos.items() if demo[1] > now}
            if topic in self._room_demos:
                return "active"
            result = publish_command(self._client, topic, uuid4().hex, target, "on", 120)
            if result.rc != 0:
                return "offline"
            self._room_demos[topic] = (target, now + 60, False)
            return "started"

    def hold_demo_load(self, topic: str, sample: Any) -> bool:
        """Give the presenter time to see the first reported ON state."""
        with self._demo_lock:
            timing = self._room_demos.get(topic)
            if timing is None:
                return False
            target, deadline, seen_on = timing
            now = monotonic()
            target_on = getattr(sample, f"{target}_on")
            other_on = any(getattr(sample, f"{load}_on") for load in LOADS if load != target)
            if now >= deadline or sample.occupied or other_on or (seen_on and not target_on):
                self._room_demos.pop(topic, None)
                return False
            if target_on and not seen_on:
                self._room_demos[topic] = (target, now + DEMO_VISIBLE_SECONDS, True)
            return True

    def start(self) -> None:
        # Step 1: Import the MQTT library only when the listener is actually started.
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.status.set_mqtt_connected(False, "paho-mqtt is not installed")
            logger.error("MQTT listener disabled: install requirements-phase4.txt")
            return

        # Step 2: Connect in the background and let paho retry when the broker drops us.
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"energy-phase4-{os.getpid()}",
            protocol=mqtt.MQTTv311,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client = client
        try:
            client.connect_async(self.settings.mqtt_broker, self.settings.mqtt_port, keepalive=60)
            client.loop_start()
        except (OSError, ValueError) as exc:
            self.status.set_mqtt_connected(False, str(exc))
            logger.error("MQTT listener could not start: %s", exc)

    def stop(self) -> None:
        client = self._client
        if client is None:
            return
        client.loop_stop()
        client.disconnect()
        self.status.set_mqtt_connected(False, None)

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code == 0:
            if self.settings.auto_load_off:
                client.subscribe(self.settings.mqtt_topic.rsplit("/", 1)[0] + "/state", qos=0)
            client.subscribe(self.settings.mqtt_topic, qos=1)
            self.status.set_mqtt_connected(True, None)
            logger.info("MQTT connected. Subscribed to %s", self.settings.mqtt_topic)
            return
        self.status.set_mqtt_connected(False, str(reason_code))
        logger.warning("MQTT connection refused: %s", reason_code)

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        # A public broker often closes idle clients. The loop reconnects on its own.
        self.status.set_mqtt_connected(False, str(reason_code))
        logger.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        # Step 3: Validate and store. Exceptions here must not kill the MQTT loop.
        try:
            if message.topic.endswith("/state"):
                if self.settings.auto_load_off and not message.retain:
                    on_ack(self.session_factory, message.topic, message.payload)
                return
            outcome = ingest_message(message.topic, message.payload, self.session_factory)
        except Exception:
            logger.exception("Unexpected error while handling a telemetry message")
            self.status.record("database_error")
            return
        self.status.record(outcome.get("status", "database_error"))
        if not self.settings.auto_load_off or message.retain or outcome["status"] != "stored":
            return
        try:
            command = on_sample(
                self.session_factory, outcome["id"], client.is_connected(),
                lambda sample: self.hold_demo_load(message.topic, sample),
            )
            if command:
                command_id, target = command
                if publish_off(client, message.topic, command_id, target).rc != 0:
                    record_failure(self.session_factory, command_id, "MQTT publish failed")
        except Exception:
            logger.exception("Could not process automatic load control")
