"""Read waste events and simulated savings from stored control_actions rows."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from phase4.control import action_status, display_status
from phase4.models import ControlAction, TelemetrySample
from phase4.savings import ENERGY_TARIFF_INR_PER_KWH, SIMULATED_SAVINGS_NOTE


def event_to_dict(row: ControlAction, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    status = action_status(row, now)
    waste_start = row.waste_started_at or row.started_at
    hold = row.hold_seconds
    power_before = row.before_w
    power_after = row.after_w
    reduction = None if power_after is None else max(power_before - power_after, 0.0)
    return {
        "event_id": row.command_id,
        "command_id": row.command_id,
        "device_id": row.device_id,
        "target": row.target,
        "status": display_status(status),
        "raw_status": status,
        "reason": "Room unoccupied while equipment was on",
        "waste_started_at": waste_start,
        "detection_at": row.detection_at,
        "hold_seconds": hold,
        "started_at": row.started_at,
        "finished_at": row.deadline if status in {"timed_out", "unconfirmed"} and row.finished_at is None else row.finished_at,
        "before_w": power_before,
        "after_w": power_after,
        "power_reduction_w": reduction,
        "mqtt_command_status": row.mqtt_command_status,
        "ack_status": row.ack_status or ("accepted" if row.ack_uptime_ms is not None else "waiting"),
        "telemetry_confirmed": bool(row.telemetry_confirmed),
        "energy_saved_wh": row.energy_saved_wh,
        "energy_saved_kwh": row.energy_saved_kwh,
        "money_saved_inr": row.money_saved_inr,
        "detail": row.detail,
        "current_is_simulated": True,
        "note": SIMULATED_SAVINGS_NOTE,
    }


def list_waste_events(
    session: Session,
    device_id: str | None,
    limit: int = 50,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    query = select(ControlAction)
    if device_id:
        query = query.where(ControlAction.device_id == device_id)
    if since is not None:
        query = query.where(ControlAction.started_at >= since)
    if until is not None:
        query = query.where(ControlAction.started_at <= until)
    query = query.order_by(ControlAction.started_at.desc()).limit(limit)
    now = datetime.now(timezone.utc)
    return [event_to_dict(row, now) for row in session.scalars(query).all()]


def get_waste_event(session: Session, device_id: str, event_id: str) -> dict[str, Any] | None:
    row = session.get(ControlAction, event_id)
    if row is None or row.device_id != device_id:
        return None
    return event_to_dict(row)


def savings_summary(session: Session, device_id: str | None = None) -> dict[str, Any]:
    query = select(ControlAction).where(ControlAction.status == "confirmed")
    if device_id:
        query = query.where(ControlAction.device_id == device_id)
    rows = list(session.scalars(query).all())
    corrections = len(rows)
    energy_wh = sum(float(row.energy_saved_wh or 0.0) for row in rows)
    money = sum(float(row.money_saved_inr or 0.0) for row in rows)
    latest = max(rows, key=lambda row: row.finished_at or row.started_at, default=None)
    latest_reduction = None
    if latest is not None and latest.after_w is not None:
        latest_reduction = max(latest.before_w - latest.after_w, 0.0)
    return {
        "device_id": device_id,
        "successful_corrections": corrections,
        "total_energy_saved_wh": energy_wh,
        "total_energy_saved_kwh": energy_wh / 1000.0,
        "total_money_saved_inr": money,
        "latest_power_reduction_w": latest_reduction,
        "tariff_inr_per_kwh": ENERGY_TARIFF_INR_PER_KWH,
        "current_is_simulated": True,
        "note": SIMULATED_SAVINGS_NOTE,
    }


def _day_bucket(value: datetime) -> date:
    return value.astimezone(timezone.utc).date()


def consumption_series(session: Session, device_id: str, days: int) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = session.execute(
        select(TelemetrySample.received_at, TelemetrySample.energy_delta_wh, TelemetrySample.cost_delta_inr)
        .where(TelemetrySample.device_id == device_id, TelemetrySample.received_at >= since)
        .order_by(TelemetrySample.received_at)
    ).all()
    buckets: dict[date, dict[str, float]] = {}
    for received_at, energy_delta_wh, cost_delta_inr in rows:
        day = _day_bucket(received_at)
        entry = buckets.setdefault(day, {"energy_wh": 0.0, "cost_inr": 0.0})
        entry["energy_wh"] += float(energy_delta_wh or 0.0)
        entry["cost_inr"] += float(cost_delta_inr or 0.0)
    return [
        {
            "date": day.isoformat(),
            "energy_wh": values["energy_wh"],
            "energy_kwh": values["energy_wh"] / 1000.0,
            "estimated_cost_inr": values["cost_inr"],
        }
        for day, values in sorted(buckets.items())
    ]


def savings_series(session: Session, device_id: str, days: int) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = session.scalars(
        select(ControlAction).where(
            ControlAction.device_id == device_id,
            ControlAction.status == "confirmed",
            ControlAction.finished_at.is_not(None),
            ControlAction.finished_at >= since,
        )
    ).all()
    buckets: dict[date, dict[str, float]] = {}
    for row in rows:
        day = _day_bucket(row.finished_at or row.started_at)
        entry = buckets.setdefault(day, {"energy_wh": 0.0, "money_inr": 0.0, "corrections": 0.0})
        entry["energy_wh"] += float(row.energy_saved_wh or 0.0)
        entry["money_inr"] += float(row.money_saved_inr or 0.0)
        entry["corrections"] += 1
    return [
        {
            "date": day.isoformat(),
            "energy_saved_wh": values["energy_wh"],
            "energy_saved_kwh": values["energy_wh"] / 1000.0,
            "money_saved_inr": values["money_inr"],
            "successful_corrections": int(values["corrections"]),
        }
        for day, values in sorted(buckets.items())
    ]


def room_analytics(session: Session, device_id: str) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "savings": savings_summary(session, device_id),
        "daily_consumption": consumption_series(session, device_id, 7),
        "weekly_consumption": consumption_series(session, device_id, 28),
        "daily_savings": savings_series(session, device_id, 7),
        "weekly_savings": savings_series(session, device_id, 28),
        "current_is_simulated": True,
        "note": SIMULATED_SAVINGS_NOTE,
    }
