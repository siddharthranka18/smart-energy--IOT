"""Save validated telemetry and read it back for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from phase4.energy import energy_interval
from phase4.models import TelemetrySample


def _optional_text(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def store_sample(session: Session, telemetry: dict[str, Any]) -> dict[str, Any]:
    """Insert one validated sample, or ignore an exact replay of a stored sample."""

    device_id = telemetry["device_id"]
    sequence = int(telemetry["sequence"])
    uptime_ms = int(telemetry["uptime_ms"])
    energy_wh = float(telemetry["energy_wh"])
    cost_inr = float(telemetry["estimated_cost_inr"])

    # Step 1: Ignore a broker replay of a sample that is already stored.
    duplicate_id = session.scalar(
        select(TelemetrySample.id)
        .where(
            TelemetrySample.device_id == device_id,
            TelemetrySample.sequence == sequence,
            TelemetrySample.uptime_ms == uptime_ms,
            func.abs(TelemetrySample.energy_wh - energy_wh) < 0.0001,
        )
        .limit(1)
    )
    if duplicate_id is not None:
        return {"status": "duplicate", "id": duplicate_id}

    # Step 2: Compare this device counter with the latest stored sample.
    previous = session.scalar(
        select(TelemetrySample)
        .where(TelemetrySample.device_id == device_id)
        .order_by(TelemetrySample.received_at.desc(), TelemetrySample.id.desc())
        .limit(1)
    )
    interval = energy_interval(
        previous.energy_wh if previous else None,
        previous.estimated_cost_inr if previous else None,
        previous.sequence if previous else None,
        previous.uptime_ms if previous else None,
        energy_wh,
        cost_inr,
        sequence,
        uptime_ms,
    )

    # Step 3: Append the historical row. The device counters are stored as sent.
    row = TelemetrySample(
        received_at=datetime.fromisoformat(telemetry["received_at"]),
        mqtt_topic=telemetry["mqtt_topic"],
        schema_version=int(telemetry["schema_version"]),
        device_id=device_id,
        firmware_version=telemetry["firmware_version"],
        sequence=sequence,
        uptime_ms=uptime_ms,
        occupied=bool(telemetry["occupied"]),
        ldr_raw=int(telemetry["ldr_raw"]),
        is_dark=bool(telemetry["is_dark"]),
        temperature_c=telemetry.get("temperature_c"),
        humidity_percent=telemetry.get("humidity_percent"),
        dht_valid=bool(telemetry["dht_valid"]),
        light_on=bool(telemetry["light_on"]),
        fan_on=bool(telemetry["fan_on"]),
        ac_on=bool(telemetry["ac_on"]),
        control_mode=_optional_text(telemetry, "control_mode"),
        current_sensor_raw=int(telemetry["current_sensor_raw"]),
        power_sensor_valid=bool(telemetry["power_sensor_valid"]),
        voltage_v=float(telemetry["voltage_v"]),
        sensor_current_a=float(telemetry["sensor_current_a"]),
        current_a=float(telemetry["current_a"]),
        load_model_power_w=float(telemetry["load_model_power_w"]),
        power_w=float(telemetry["power_w"]),
        energy_wh=energy_wh,
        energy_kwh=float(telemetry["energy_kwh"]),
        estimated_cost_inr=cost_inr,
        high_power_alert=bool(telemetry["high_power_alert"]),
        unoccupied_power_alert=bool(telemetry["unoccupied_power_alert"]),
        energy_delta_wh=interval.energy_delta_wh,
        cost_delta_inr=interval.cost_delta_inr,
        device_counter_reset=interval.device_counter_reset,
    )
    session.add(row)
    session.flush()
    return {
        "status": "stored",
        "id": row.id,
        "energy_delta_wh": interval.energy_delta_wh,
        "cost_delta_inr": interval.cost_delta_inr,
        "device_counter_reset": interval.device_counter_reset,
    }


def sample_to_dict(row: TelemetrySample) -> dict[str, Any]:
    """Return the stored columns for an API response."""

    return {
        "id": row.id,
        "received_at": row.received_at,
        "mqtt_topic": row.mqtt_topic,
        "schema_version": row.schema_version,
        "device_id": row.device_id,
        "firmware_version": row.firmware_version,
        "sequence": row.sequence,
        "uptime_ms": row.uptime_ms,
        "occupied": row.occupied,
        "ldr_raw": row.ldr_raw,
        "is_dark": row.is_dark,
        "temperature_c": row.temperature_c,
        "humidity_percent": row.humidity_percent,
        "dht_valid": row.dht_valid,
        "light_on": row.light_on,
        "fan_on": row.fan_on,
        "ac_on": row.ac_on,
        "control_mode": row.control_mode,
        "current_sensor_raw": row.current_sensor_raw,
        "power_sensor_valid": row.power_sensor_valid,
        "voltage_v": row.voltage_v,
        "sensor_current_a": row.sensor_current_a,
        "current_a": row.current_a,
        "load_model_power_w": row.load_model_power_w,
        "power_w": row.power_w,
        "energy_wh": row.energy_wh,
        "energy_kwh": row.energy_kwh,
        "estimated_cost_inr": row.estimated_cost_inr,
        "high_power_alert": row.high_power_alert,
        "unoccupied_power_alert": row.unoccupied_power_alert,
        "energy_delta_wh": row.energy_delta_wh,
        "cost_delta_inr": row.cost_delta_inr,
        "device_counter_reset": row.device_counter_reset,
    }


def latest_sample(session: Session, device_id: str) -> TelemetrySample | None:
    return session.scalar(
        select(TelemetrySample)
        .where(TelemetrySample.device_id == device_id)
        .order_by(TelemetrySample.received_at.desc(), TelemetrySample.id.desc())
        .limit(1)
    )


def list_rooms(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            TelemetrySample.device_id,
            func.count(TelemetrySample.id),
            func.max(TelemetrySample.received_at),
            func.coalesce(func.sum(TelemetrySample.energy_delta_wh), 0.0),
            func.coalesce(func.sum(TelemetrySample.cost_delta_inr), 0.0),
        )
        .group_by(TelemetrySample.device_id)
        .order_by(TelemetrySample.device_id)
    ).all()
    return [
        {
            "device_id": device_id,
            "sample_count": int(sample_count),
            "last_received_at": last_received_at,
            "server_energy_wh": float(server_energy_wh),
            "server_energy_kwh": float(server_energy_wh) / 1000.0,
            "server_cost_inr": float(server_cost_inr),
        }
        for device_id, sample_count, last_received_at, server_energy_wh, server_cost_inr in rows
    ]


def list_samples(session: Session, device_id: str, limit: int, alerts_only: bool) -> list[TelemetrySample]:
    query = select(TelemetrySample).where(TelemetrySample.device_id == device_id)
    if alerts_only:
        query = query.where(
            or_(
                TelemetrySample.high_power_alert.is_(True),
                TelemetrySample.unoccupied_power_alert.is_(True),
            )
        )
    query = query.order_by(TelemetrySample.received_at.desc(), TelemetrySample.id.desc()).limit(limit)
    return list(session.scalars(query).all())


def energy_summary(session: Session, device_id: str) -> dict[str, Any] | None:
    """Sum the stored intervals. This total survives a device counter reset."""

    latest = latest_sample(session, device_id)
    if latest is None:
        return None

    sample_count, server_energy_wh, server_cost_inr, reset_count, first_received_at, last_received_at = (
        session.execute(
            select(
                func.count(TelemetrySample.id),
                func.coalesce(func.sum(TelemetrySample.energy_delta_wh), 0.0),
                func.coalesce(func.sum(TelemetrySample.cost_delta_inr), 0.0),
                func.count(TelemetrySample.id).filter(TelemetrySample.device_counter_reset.is_(True)),
                func.min(TelemetrySample.received_at),
                func.max(TelemetrySample.received_at),
            ).where(TelemetrySample.device_id == device_id)
        ).one()
    )
    server_energy_wh = float(server_energy_wh)
    return {
        "device_id": device_id,
        "sample_count": int(sample_count),
        "device_counter_resets": int(reset_count),
        "first_received_at": first_received_at,
        "last_received_at": last_received_at,
        "server_energy_wh": server_energy_wh,
        "server_energy_kwh": server_energy_wh / 1000.0,
        "server_cost_inr": float(server_cost_inr),
        "latest_device_energy_wh": latest.energy_wh,
        "latest_device_energy_kwh": latest.energy_kwh,
        "latest_device_cost_inr": latest.estimated_cost_inr,
        "latest_power_w": latest.power_w,
        "latest_sensor_current_a": latest.sensor_current_a,
    }
