"""Validation and alert rules for Phase 3 MQTT energy telemetry.

This module intentionally uses only the Python standard library so its logic can
be tested without a broker or the optional paho-mqtt runtime dependency.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any


TOPIC_PREFIX = "smart-energy-demo/siddharthranka18-smart-energy-2026"
TELEMETRY_TOPIC = f"{TOPIC_PREFIX}/+/telemetry"
HIGH_POWER_THRESHOLD_W = 1800.0
UNOCCUPIED_POWER_THRESHOLD_W = 10.0

_TOPIC_RE = re.compile(
    rf"^{re.escape(TOPIC_PREFIX)}/(?P<device_id>[A-Za-z0-9_-]+)/telemetry$"
)


class TelemetryValidationError(ValueError):
    """Raised when an MQTT telemetry message violates the Phase 3 contract."""


def _number(payload: dict[str, Any], name: str, minimum: float, maximum: float) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TelemetryValidationError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise TelemetryValidationError(f"{name} is outside the allowed range")
    return value


def _boolean(payload: dict[str, Any], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        raise TelemetryValidationError(f"{name} must be boolean")
    return value


def validate_telemetry(topic: str, raw_payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize one room telemetry message."""

    topic_match = _TOPIC_RE.fullmatch(topic)
    if not topic_match:
        raise TelemetryValidationError("topic does not match the Phase 3 telemetry contract")

    if isinstance(raw_payload, bytes):
        try:
            raw_payload = raw_payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TelemetryValidationError("payload is not valid UTF-8") from exc

    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise TelemetryValidationError("payload is not valid JSON") from exc
    elif isinstance(raw_payload, dict):
        payload = dict(raw_payload)
    else:
        raise TelemetryValidationError("payload must be JSON text, bytes, or an object")

    if payload.get("schema_version") != 1:
        raise TelemetryValidationError("unsupported schema_version")
    if payload.get("message_type") != "telemetry":
        raise TelemetryValidationError("message_type must be telemetry")

    topic_device = topic_match.group("device_id")
    if payload.get("device_id") != topic_device:
        raise TelemetryValidationError("device_id does not match the MQTT topic")
    if not isinstance(payload.get("firmware_version"), str) or not payload["firmware_version"]:
        raise TelemetryValidationError("firmware_version is required")

    sequence = payload.get("sequence")
    uptime_ms = payload.get("uptime_ms")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise TelemetryValidationError("sequence must be a positive integer")
    if isinstance(uptime_ms, bool) or not isinstance(uptime_ms, int) or uptime_ms < 0:
        raise TelemetryValidationError("uptime_ms must be a non-negative integer")

    for field in (
        "occupied",
        "is_dark",
        "dht_valid",
        "light_on",
        "fan_on",
        "ac_on",
        "power_sensor_valid",
        "high_power_alert",
        "unoccupied_power_alert",
    ):
        _boolean(payload, field)

    ldr_raw = payload.get("ldr_raw")
    sensor_raw = payload.get("current_sensor_raw")
    if isinstance(ldr_raw, bool) or not isinstance(ldr_raw, int) or not 0 <= ldr_raw <= 4095:
        raise TelemetryValidationError("ldr_raw must be an integer from 0 to 4095")
    if isinstance(sensor_raw, bool) or not isinstance(sensor_raw, int) or not 0 <= sensor_raw <= 4095:
        raise TelemetryValidationError("current_sensor_raw must be an integer from 0 to 4095")

    for field, low, high in (
        ("voltage_v", 0.0, 300.0),
        ("sensor_current_a", 0.0, 100.0),
        ("current_a", 0.0, 100.0),
        ("load_model_power_w", 0.0, 30000.0),
        ("power_w", 0.0, 30000.0),
        ("energy_wh", 0.0, 1.0e9),
        ("energy_kwh", 0.0, 1.0e6),
        ("estimated_cost_inr", 0.0, 1.0e9),
    ):
        _number(payload, field, low, high)

    for field, low, high in (
        ("temperature_c", -40.0, 125.0),
        ("humidity_percent", 0.0, 100.0),
    ):
        if payload.get(field) is not None:
            _number(payload, field, low, high)

    if payload["dht_valid"] and (
        payload.get("temperature_c") is None or payload.get("humidity_percent") is None
    ):
        raise TelemetryValidationError("valid DHT data requires temperature and humidity")

    payload["received_at"] = datetime.now(timezone.utc).isoformat()
    payload["mqtt_topic"] = topic
    return payload


def evaluate_alerts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate server-side energy alerts from a validated telemetry object."""

    alerts: list[dict[str, Any]] = []
    power_w = float(payload["power_w"])
    if power_w >= HIGH_POWER_THRESHOLD_W:
        alerts.append(
            {
                "alert_code": "high_power_consumption",
                "severity": "high",
                "device_id": payload["device_id"],
                "power_w": power_w,
            }
        )
    if not payload["occupied"] and power_w >= UNOCCUPIED_POWER_THRESHOLD_W:
        alerts.append(
            {
                "alert_code": "power_in_unoccupied_room",
                "severity": "warning",
                "device_id": payload["device_id"],
                "power_w": power_w,
            }
        )
    return alerts


def build_ingestion_record(topic: str, raw_payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    telemetry = validate_telemetry(topic, raw_payload)
    return {"event": "telemetry_accepted", "telemetry": telemetry, "alerts": evaluate_alerts(telemetry)}
