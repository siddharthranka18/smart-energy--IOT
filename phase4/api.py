"""REST endpoints for the stored room history."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from phase4.config import SIMULATED_MEASUREMENT_NOTE
from phase4.storage import energy_summary, latest_sample, list_rooms, list_samples, sample_to_dict


router = APIRouter()
_DEVICE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


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
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "database_error": database_error,
        "mqtt_enabled": request.app.state.settings.mqtt_enabled,
        "mqtt_broker": request.app.state.settings.mqtt_broker,
        "mqtt_topic": request.app.state.settings.mqtt_topic,
        **mqtt,
        "current_is_simulated": True,
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
