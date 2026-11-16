"""Shut off loads in an empty room and verify the resulting MQTT command."""

import json
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select

from phase4.models import ControlAction, TelemetrySample


DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
VERIFY_WINDOW = timedelta(seconds=120)
RETRY_DELAY = timedelta(seconds=60)
LOADS = ("light", "fan", "ac")


def target_fields(target):
    return tuple(f"{load}_on" for load in (LOADS if target == "all" else (target,)))


def action_status(action, now):
    if action.status == "pending" and now >= action.deadline:
        return "timed_out"
    return action.status


def on_sample(session_factory, sample_id, can_send):
    """Reserve at most one command per room and require post-ack telemetry."""
    now = datetime.now(timezone.utc)
    with session_factory.begin() as session:
        sample = session.get(TelemetrySample, sample_id)
        if not DEVICE_ID.fullmatch(sample.device_id):
            return None
        session.execute(select(func.pg_advisory_xact_lock(func.hashtext("energy-control:" + sample.device_id))))
        action = session.scalar(select(ControlAction)
            .where(ControlAction.device_id == sample.device_id)
            .order_by(ControlAction.started_at.desc()).limit(1).with_for_update())
        if action and action.status == "pending":
            if now >= action.deadline:
                action.status = "timed_out"
                action.finished_at = action.deadline
            elif (action.ack_uptime_ms is not None
                    and sample.received_at > action.started_at
                    and sample.sequence > action.before_sequence
                    and sample.uptime_ms > action.ack_uptime_ms
                    and all(getattr(sample, field) is False for field in target_fields(action.target))):
                action.status = "confirmed"
                action.after_w = sample.power_w
                action.finished_at = sample.received_at
                return None
            else:
                return None
        active_loads = [load for load in LOADS if getattr(sample, f"{load}_on")]
        if (not can_send or sample.occupied or not active_loads
                or now - sample.received_at > timedelta(seconds=10)
                or (action and action.status != "confirmed" and now < action.deadline + RETRY_DELAY)):
            return None
        target = active_loads[0] if len(active_loads) == 1 else "all"
        command_id = uuid4().hex
        session.add(ControlAction(
            command_id=command_id, device_id=sample.device_id, status="pending", target=target,
            started_at=now, deadline=now + VERIFY_WINDOW, before_w=sample.power_w,
            before_sequence=sample.sequence, before_uptime_ms=sample.uptime_ms,
        ))
        return command_id, target


def publish_off(client, telemetry_topic, command_id, target):
    room_topic, _ = telemetry_topic.rsplit("/", 1)
    device_id = room_topic.rsplit("/", 1)[-1]
    payload = {
        "schema_version": 1, "command_id": command_id, "device_id": device_id,
        "target": target, "action": "off", "mode": "manual", "expires_in_seconds": 30,
    }
    return client.publish(room_topic + "/command", json.dumps(payload), qos=0, retain=False)


def record_failure(session_factory, command_id, detail):
    with session_factory.begin() as session:
        action = session.get(ControlAction, command_id, with_for_update=True)
        if action.status == "pending":
            action.status = "failed"
            action.detail = detail
            action.finished_at = datetime.now(timezone.utc)


def on_ack(session_factory, topic, payload):
    try:
        report = json.loads(payload)
    except (ValueError, UnicodeError):
        return
    if not isinstance(report, dict) or report.get("message_type") != "command_result":
        return
    _, device_id, _ = topic.rsplit("/", 2)
    command_id = report.get("command_id")
    uptime = report.get("uptime_ms")
    if (report.get("schema_version") != 1 or report.get("device_id") != device_id
            or not isinstance(command_id, str) or not re.fullmatch(r"[0-9a-f]{32}", command_id)
            or type(uptime) is not int or uptime < 0 or type(report.get("accepted")) is not bool):
        return
    now = datetime.now(timezone.utc)
    with session_factory.begin() as session:
        action = session.get(ControlAction, command_id, with_for_update=True)
        if (action is None or action.device_id != device_id or action_status(action, now) != "pending"
                or uptime < action.before_uptime_ms or action.ack_uptime_ms is not None):
            return
        if report["accepted"] and all(report.get(field) is False for field in target_fields(action.target)):
            action.ack_uptime_ms = uptime
        else:
            action.status = "failed"
            action.detail = "Device rejected the command or did not report every targeted load off"
            action.finished_at = now
