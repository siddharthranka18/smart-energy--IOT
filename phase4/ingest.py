"""Validate one MQTT payload and store it. Database failures stay inside this function."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from phase3.telemetry_core import TelemetryValidationError, validate_telemetry
from phase4.storage import store_sample


logger = logging.getLogger("phase4")


def ingest_message(topic: str, raw_payload: bytes | str | dict[str, Any], session_factory: Any) -> dict[str, Any]:
    """Validate a telemetry payload and append it to history."""

    # Step 1: Reject anything that does not match the firmware contract.
    try:
        telemetry = validate_telemetry(topic, raw_payload)
    except TelemetryValidationError as exc:
        logger.warning("Rejected telemetry on %s: %s", topic, exc)
        return {"status": "rejected", "reason": str(exc)}

    # Step 2: Store the accepted sample. A database error must not stop the listener.
    try:
        with session_factory() as session:
            outcome = store_sample(session, telemetry)
            session.commit()
    except SQLAlchemyError as exc:
        logger.error("Database error while storing telemetry from %s: %s", topic, exc)
        return {"status": "database_error", "reason": "database write failed"}

    if outcome["status"] == "stored":
        logger.info(
            "Stored %s sequence %s power %.1f W energy delta %.4f Wh",
            telemetry["device_id"],
            telemetry["sequence"],
            float(telemetry["power_w"]),
            outcome["energy_delta_wh"],
        )
        if outcome["device_counter_reset"]:
            logger.info("Device energy counter restarted for %s. Server history was kept.", telemetry["device_id"])
    return outcome
