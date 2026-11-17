"""Runtime settings for the Phase 4 backend.

The default database URL matches the local demo database described in
PHASE_4_VERIFICATION.md. Environment variables and a project .env file
override it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from phase3.telemetry_core import TELEMETRY_TOPIC


DEFAULT_DATABASE_URL = "postgresql+psycopg://energy:energy@127.0.0.1:5432/smart_energy"

SIMULATED_MEASUREMENT_NOTE = (
    "Current and power are simulated by the ESP32 firmware. "
    "The supply voltage is the fixed value published by the device. "
    "Server energy and cost add up the stored intervals, so they remain "
    "after the ESP32 restarts and its own counters return to zero."
)


@dataclass(frozen=True)
class Settings:
    database_url: str
    mqtt_broker: str
    mqtt_port: int
    mqtt_topic: str
    mqtt_enabled: bool
    api_host: str
    api_port: int
    auto_load_off: bool = False
    # Demo 30s, normal test 60s, report example 300s. One setting for the whole backend.
    waste_hold_seconds: int = 30


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off"}


def _seconds(name: str, default: str) -> int:
    raw = os.getenv(name, default).strip()
    try:
        value = int(raw)
    except ValueError:
        value = int(default)
    return max(0, min(value, 3600))


def load_settings() -> Settings:
    # A local .env file is optional. Real environment variables win.
    load_dotenv()
    return Settings(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).strip(),
        mqtt_broker=os.getenv("MQTT_BROKER", "broker.hivemq.com").strip(),
        mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
        mqtt_topic=os.getenv("MQTT_TELEMETRY_TOPIC", TELEMETRY_TOPIC).strip(),
        mqtt_enabled=_flag("MQTT_ENABLED", "1"),
        api_host=os.getenv("API_HOST", "127.0.0.1").strip(),
        api_port=int(os.getenv("API_PORT", "8000")),
        auto_load_off=_flag("AUTO_LOAD_OFF", os.getenv("AUTO_LIGHT_OFF", "0")),
        waste_hold_seconds=_seconds("WASTE_HOLD_SECONDS", "30"),
    )
