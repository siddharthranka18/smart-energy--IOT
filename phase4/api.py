"""REST endpoints for the stored room history and Phase 6 savings analytics."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request
from paho.mqtt.client import topic_matches_sub
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from phase4.analytics import (
    event_to_dict,
    get_waste_event,
    list_waste_events,
    room_analytics,
    savings_summary,
)
from phase4.config import SIMULATED_MEASUREMENT_NOTE
from phase4.control import LOADS, RETRY_DELAY, action_status, display_status, publish_command
from phase4.models import ControlAction
from phase4.savings import SIMULATED_SAVINGS_NOTE
from phase4.storage import energy_summary, latest_sample, list_rooms, list_samples, sample_to_dict


router = APIRouter()
_DEVICE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class ManualCommand(BaseModel):
    target: str = Field(pattern="^(light|fan|ac|all|automatic)$")
    action: str = Field(pattern="^(on|off)$")
    expires_in_seconds: int = Field(default=60, ge=1, le=3600)


def _require_device_id(device_id: str) -> str:
    if not _DEVICE_ID.fullmatch(device_id):
        raise HTTPException(status_code=400, detail="device_id contains unsupported characters.")
    return device_id


def _run(request: Request, work: Any) -> Any:
    """Open a session, run one read, and turn a database failure into HTTP 503."""

    if request.app.state.database_error or request.app.state.session_factory is None:
        raise HTTPException(status_code=503, detail="Database is unavailable.")
    session = request.app.state.session_factory()
    try:
        return work(session)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    finally:
        session.close()


def _parse_time(value: str | None, name: str) -> datetime | None:
    if value is None or value.strip() == "":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {name}. Use ISO-8601.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    database = "ok"
    database_error = request.app.state.database_error
    factory = request.app.state.session_factory
    if database_error or factory is None:
        database = "unavailable"
    else:
        try:
            with factory() as session:
                session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            database = "unavailable"
            database_error = str(exc)

    mqtt = request.app.state.status.snapshot()
    settings = request.app.state.settings
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "database_error": database_error,
        "mqtt_enabled": settings.mqtt_enabled,
        "auto_light_off": settings.auto_load_off,
        "auto_load_off": settings.auto_load_off,
        "waste_hold_seconds": settings.waste_hold_seconds,
        "light_demo_available": settings.auto_load_off and settings.mqtt_enabled,
        "equipment_demo_available": settings.auto_load_off and settings.mqtt_enabled,
        "manual_controls_available": settings.mqtt_enabled,
        "mqtt_broker": settings.mqtt_broker,
        "mqtt_topic": settings.mqtt_topic,
        **mqtt,
        "current_is_simulated": True,
        "note": SIMULATED_SAVINGS_NOTE,
    }


@router.get("/rooms")
def rooms(request: Request) -> dict[str, Any]:
    rooms_found = _run(request, list_rooms)
    return {"rooms": rooms_found, "current_is_simulated": True}


@router.get("/rooms/{device_id}")
def room(device_id: str, request: Request) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    row = _run(request, lambda session: latest_sample(session, device_id))
    if row is None:
        raise HTTPException(status_code=404, detail="No telemetry stored for this room yet.")
    body = sample_to_dict(row)
    body["current_is_simulated"] = True
    body["note"] = SIMULATED_MEASUREMENT_NOTE
    return body


@router.get("/rooms/{device_id}/telemetry")
def telemetry(
    device_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    rows = _run(request, lambda session: list_samples(session, device_id, limit, alerts_only=False))
    return {
        "device_id": device_id,
        "count": len(rows),
        "samples": [sample_to_dict(row) for row in rows],
    }


@router.get("/rooms/{device_id}/energy")
def energy(device_id: str, request: Request) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    summary = _run(request, lambda session: energy_summary(session, device_id))
    if summary is None:
        raise HTTPException(status_code=404, detail="No telemetry stored for this room yet.")
    summary["current_is_simulated"] = True
    summary["note"] = SIMULATED_MEASUREMENT_NOTE
    return summary


@router.get("/rooms/{device_id}/alerts")
def alerts(
    device_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=500),
) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    rows = _run(request, lambda session: list_samples(session, device_id, limit, alerts_only=True))
    return {
        "device_id": device_id,
        "count": len(rows),
        "alerts": [sample_to_dict(row) for row in rows],
    }


@router.get("/rooms/{device_id}/control-actions")
def control_actions(device_id: str, request: Request) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    rows = _run(request, lambda session: list(session.scalars(
        select(ControlAction).where(ControlAction.device_id == device_id)
        .order_by(ControlAction.started_at.desc()).limit(10)
    )))
    now = datetime.now(timezone.utc)
    actions = []
    for row in rows:
        body = event_to_dict(row, now)
        body["status"] = action_status(row, now)
        body["display_status"] = display_status(body["status"])
        actions.append(body)
    return {"actions": actions, "note": SIMULATED_SAVINGS_NOTE}


@router.get("/rooms/{device_id}/waste-events")
def waste_events(
    device_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    events = _run(
        request,
        lambda session: list_waste_events(
            session, device_id, limit, _parse_time(since, "since"), _parse_time(until, "until"),
        ),
    )
    return {"device_id": device_id, "count": len(events), "events": events, "note": SIMULATED_SAVINGS_NOTE}


@router.get("/rooms/{device_id}/waste-events/{event_id}")
def waste_event(device_id: str, event_id: str, request: Request) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    event = _run(request, lambda session: get_waste_event(session, device_id, event_id))
    if event is None:
        raise HTTPException(status_code=404, detail="Waste event not found.")
    return event


@router.get("/rooms/{device_id}/savings")
def savings(device_id: str, request: Request) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    return _run(request, lambda session: savings_summary(session, device_id))


@router.get("/rooms/{device_id}/analytics")
def analytics(device_id: str, request: Request) -> dict[str, Any]:
    device_id = _require_device_id(device_id)
    return _run(request, lambda session: room_analytics(session, device_id))


@router.get("/savings")
def global_savings(request: Request) -> dict[str, Any]:
    return _run(request, lambda session: savings_summary(session, None))


@router.post("/rooms/{device_id}/commands", status_code=202)
def manual_command(device_id: str, body: ManualCommand, request: Request) -> dict[str, Any]:
    """Send a one-shot MQTT command. Separate from the automatic waste demo buttons."""

    device_id = _require_device_id(device_id)
    settings = request.app.state.settings
    listener = request.app.state.listener
    if listener is None or getattr(listener, "_client", None) is None:
        raise HTTPException(status_code=503, detail="MQTT is unavailable.")
    if body.target == "all" and body.action != "off":
        raise HTTPException(status_code=400, detail="target all only supports action off.")
    if body.target == "automatic" and body.action not in {"on", "off"}:
        raise HTTPException(status_code=400, detail="Invalid automatic command.")

    sample = _run(request, lambda session: latest_sample(session, device_id))
    if sample is None or datetime.now(timezone.utc) - sample.received_at > timedelta(seconds=30):
        raise HTTPException(status_code=409, detail="Start Wokwi and wait for a fresh room reading.")
    if body.target in {"fan", "ac"} and body.action == "on" and not sample.dht_valid:
        raise HTTPException(status_code=409, detail="Fan and AC ON are blocked while the DHT22 reading is invalid.")
    if not topic_matches_sub(settings.mqtt_topic, sample.mqtt_topic):
        raise HTTPException(status_code=409, detail="Room topic is outside the configured subscription.")

    command_id = uuid4().hex
    target = body.target
    action = "off" if target == "automatic" else body.action
    result = publish_command(
        listener._client, sample.mqtt_topic, command_id, target, action, body.expires_in_seconds,
    )
    if result.rc != 0:
        raise HTTPException(status_code=503, detail="MQTT publish failed.")
    return {
        "status": "accepted",
        "command_id": command_id,
        "device_id": device_id,
        "target": target,
        "action": action,
        "note": "Manual command published. Automatic waste events are tracked separately.",
    }


@router.post("/rooms/{device_id}/{target}-demo", status_code=202)
def equipment_demo(device_id: str, target: str, request: Request, x_demo_intent: str = Header()) -> dict[str, str]:
    device_id = _require_device_id(device_id)
    if target not in LOADS or x_demo_intent != f"{target}-demo":
        raise HTTPException(status_code=400, detail="Invalid demo request.")
    settings = request.app.state.settings
    listener = request.app.state.listener
    if not settings.auto_load_off:
        raise HTTPException(status_code=409, detail="Automatic equipment shutoff must be enabled for this demo.")
    if listener is None:
        raise HTTPException(status_code=503, detail="MQTT is unavailable.")

    def read_room(session):
        action = session.scalar(select(ControlAction).where(ControlAction.device_id == device_id)
            .order_by(ControlAction.started_at.desc()).limit(1))
        return latest_sample(session, device_id), action

    sample, action = _run(request, read_room)
    now = datetime.now(timezone.utc)
    if (sample is None or now - sample.received_at > timedelta(seconds=30)
            or not topic_matches_sub(settings.mqtt_topic, sample.mqtt_topic)):
        raise HTTPException(status_code=409, detail="Start Wokwi and wait for a fresh room reading.")
    if sample.occupied or sample.light_on or sample.fan_on or sample.ac_on:
        raise HTTPException(status_code=409, detail="Wait until the room is empty and all equipment is off.")
    if target in ("fan", "ac") and not sample.dht_valid:
        raise HTTPException(status_code=409, detail="Wait for a valid temperature reading from the DHT22.")
    if action and action.status in {"watching", "pending"}:
        raise HTTPException(status_code=409, detail="The previous shutoff is still pending or cooling down.")
    if action and action.status != "confirmed" and action.status != "cancelled":
        finished = action.finished_at or action.deadline
        if now < finished + RETRY_DELAY:
            raise HTTPException(status_code=409, detail="The previous shutoff is still pending or cooling down.")
    outcome = listener.start_equipment_demo(sample.mqtt_topic, target)
    if outcome == "active":
        raise HTTPException(status_code=409, detail="An equipment demo is already running for this room.")
    if outcome == "offline":
        raise HTTPException(status_code=503, detail="MQTT is unavailable. Wait for it to reconnect.")
    return {"status": outcome}
