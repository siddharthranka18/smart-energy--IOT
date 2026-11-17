"""Empty-room waste detection, hold timer, OFF command, and confirmation."""

import json
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select

from phase4.models import ControlAction, TelemetrySample
from phase4.savings import compute_savings


DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
VERIFY_WINDOW = timedelta(seconds=120)
RETRY_DELAY = timedelta(seconds=60)
LOADS = ("light", "fan", "ac")
ACTIVE_STATUSES = ("watching", "pending")
FINISHED_RETRY_STATUSES = ("timed_out", "unconfirmed", "failed")


def target_fields(target):
    return tuple(f"{load}_on" for load in (LOADS if target == "all" else (target,)))


def action_status(action, now):
    if action.status == "pending" and now >= action.deadline:
        return "unconfirmed" if action.ack_uptime_ms is None else "timed_out"
    if action.status == "timed_out" and action.ack_uptime_ms is None:
        return "unconfirmed"
    return action.status


def display_status(status):
    return {
        "watching": "pending",
        "pending": "pending",
        "confirmed": "confirmed",
        "failed": "failed",
        "cancelled": "cancelled",
        "timed_out": "unconfirmed",
        "unconfirmed": "unconfirmed",
    }.get(status, status)


def on_sample(session_factory, sample_id, can_send, hold_demo_load=None, hold_seconds=30):
    """Watch empty-room waste, wait hold_seconds, then send one OFF command."""

    now = datetime.now(timezone.utc)
    hold = timedelta(seconds=max(0, int(hold_seconds)))
    with session_factory.begin() as session:
        sample = session.get(TelemetrySample, sample_id)
        if not DEVICE_ID.fullmatch(sample.device_id):
            return None
        session.execute(select(func.pg_advisory_xact_lock(func.hashtext("energy-control:" + sample.device_id))))
        action = session.scalar(select(ControlAction)
            .where(ControlAction.device_id == sample.device_id)
            .order_by(ControlAction.started_at.desc()).limit(1).with_for_update())

        # Step 1: Confirm or time out a command that was already sent.
        if action and action.status == "pending":
            if now >= action.deadline:
                action.status = "unconfirmed" if action.ack_uptime_ms is None else "timed_out"
                action.finished_at = action.deadline
                action.detail = action.detail or "Confirmation timed out"
            elif (action.ack_uptime_ms is not None
                    and sample.received_at > action.started_at
                    and sample.sequence > action.before_sequence
                    and sample.uptime_ms > action.ack_uptime_ms
                    and all(getattr(sample, field) is False for field in target_fields(action.target))):
                action.status = "confirmed"
                action.after_w = sample.power_w
                action.finished_at = sample.received_at
                action.telemetry_confirmed = True
                _apply_savings(action, sample.received_at)
            return None

        active_loads = [load for load in LOADS if getattr(sample, f"{load}_on")]
        demo_hold = hold_demo_load is not None and hold_demo_load(sample)

        # Step 2: Advance or cancel an open waste watch.
        if action and action.status == "watching":
            if sample.occupied:
                action.status = "cancelled"
                action.finished_at = now
                action.detail = "Occupancy returned before the hold timer expired"
                return None
            if not active_loads:
                action.status = "cancelled"
                action.finished_at = now
                action.detail = "Equipment turned off before the hold timer expired"
                return None
            if now - (action.waste_started_at or action.started_at) < hold or demo_hold or not can_send:
                return None
            action.target = active_loads[0] if len(active_loads) == 1 else "all"
            action.status = "pending"
            action.detection_at = now
            action.started_at = now
            action.deadline = now + VERIFY_WINDOW
            action.before_w = sample.power_w
            action.before_sequence = sample.sequence
            action.before_uptime_ms = sample.uptime_ms
            action.mqtt_command_status = "sent"
            return action.command_id, action.target

        # Step 3: Start a new watch when the empty room still has a load on.
        if (sample.occupied or not active_loads
                or now - sample.received_at > timedelta(seconds=10)):
            return None
        if action and action.status in ACTIVE_STATUSES:
            return None
        if action and action.status in FINISHED_RETRY_STATUSES:
            finished = action.finished_at or action.deadline
            if now < finished + RETRY_DELAY:
                return None
        if action and action.status == "cancelled" and action.finished_at and now < action.finished_at + timedelta(seconds=5):
            return None

        target = active_loads[0] if len(active_loads) == 1 else "all"
        command_id = uuid4().hex
        action = ControlAction(
            command_id=command_id, device_id=sample.device_id, status="watching", target=target,
            started_at=now, deadline=now + hold + VERIFY_WINDOW, before_w=sample.power_w,
            before_sequence=sample.sequence, before_uptime_ms=sample.uptime_ms,
            waste_started_at=now, hold_seconds=int(hold.total_seconds()),
            mqtt_command_status="waiting", ack_status="waiting", telemetry_confirmed=False,
        )
        session.add(action)
        # Hold of zero seconds: send OFF on this same sample when demos are not holding.
        if hold.total_seconds() == 0 and can_send and not demo_hold:
            action.status = "pending"
            action.detection_at = now
            action.deadline = now + VERIFY_WINDOW
            action.mqtt_command_status = "sent"
            return command_id, target
        return None


def _apply_savings(action, confirmed_at):
    reduction, energy_wh, energy_kwh, money = compute_savings(
        action.before_w, action.after_w or 0.0, action.waste_started_at or action.started_at, confirmed_at,
    )
    action.energy_saved_wh = energy_wh
    action.energy_saved_kwh = energy_kwh
    action.money_saved_inr = money
    if reduction <= 0:
        action.detail = (action.detail or "") + (" " if action.detail else "") + "No positive power reduction"


def publish_command(client, telemetry_topic, command_id, target, action, expires_in_seconds):
    room_topic, _ = telemetry_topic.rsplit("/", 1)
    device_id = room_topic.rsplit("/", 1)[-1]
    payload = {
        "schema_version": 1, "command_id": command_id, "device_id": device_id,
        "target": target, "action": action, "mode": "manual", "expires_in_seconds": expires_in_seconds,
    }
    return client.publish(room_topic + "/command", json.dumps(payload), qos=0, retain=False)


def publish_off(client, telemetry_topic, command_id, target):
    return publish_command(client, telemetry_topic, command_id, target, "off", 30)


def record_failure(session_factory, command_id, detail):
    with session_factory.begin() as session:
        action = session.get(ControlAction, command_id, with_for_update=True)
        if action and action.status == "pending":
            action.status = "failed"
            action.mqtt_command_status = "failed"
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
            action.ack_status = "accepted"
        else:
            action.status = "failed"
            action.ack_status = "rejected"
            action.detail = "Device rejected the command or did not report every targeted load off"
            action.finished_at = now
