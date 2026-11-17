import json
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import SQLAlchemyError

from phase4.config import Settings
from phase4.main import create_app
from phase4.models import ControlAction, TelemetrySample
from phase4.mqtt_listener import TelemetryListener
from phase4.savings import compute_savings


TOPIC = "smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/telemetry"
TEST_DATABASE_URL = os.getenv(
    "PHASE4_TEST_DATABASE_URL",
    "postgresql+psycopg://energy:energy@127.0.0.1:5432/smart_energy_test",
)


def _database_is_reachable() -> bool:
    engine = create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
    finally:
        engine.dispose()


def _payload(**overrides):
    body = {
        "schema_version": 1,
        "message_type": "telemetry",
        "device_id": "room-1",
        "firmware_version": "3.0.0",
        "sequence": 1,
        "uptime_ms": 2000,
        "occupied": False,
        "ldr_raw": 2200,
        "is_dark": True,
        "temperature_c": 30.5,
        "humidity_percent": 55.0,
        "dht_valid": True,
        "light_on": True,
        "fan_on": False,
        "ac_on": False,
        "control_mode": "automatic",
        "current_sensor_raw": 0,
        "power_sensor_valid": True,
        "voltage_v": 230.0,
        "sensor_current_a": 0.0,
        "current_a": 0.087,
        "load_model_power_w": 20.0,
        "power_w": 20.0,
        "energy_wh": 1.0,
        "energy_kwh": 0.001,
        "estimated_cost_inr": 0.008,
        "high_power_alert": False,
        "unoccupied_power_alert": True,
    }
    body.update(overrides)
    return body


class SavingsFormulaTests(unittest.TestCase):
    def test_positive_reduction_and_tariff(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)
        reduction, wh, kwh, money = compute_savings(20, 0, start, end)
        self.assertEqual(reduction, 20)
        self.assertEqual(wh, 40)
        self.assertEqual(kwh, 0.04)
        self.assertAlmostEqual(money, 0.32)

    def test_zero_or_negative_reduction_has_no_positive_savings(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=1)
        self.assertEqual(compute_savings(10, 10, start, end)[1:], (0.0, 0.0, 0.0))
        self.assertEqual(compute_savings(5, 12, start, end)[1:], (0.0, 0.0, 0.0))


@unittest.skipUnless(_database_is_reachable(), "PostgreSQL test database is not running")
class Phase6WasteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = Settings(
            database_url=TEST_DATABASE_URL,
            mqtt_broker="broker.hivemq.com",
            mqtt_port=1883,
            mqtt_topic=TOPIC.replace("room-1", "+"),
            mqtt_enabled=False,
            api_host="127.0.0.1",
            api_port=8000,
            auto_load_off=True,
            waste_hold_seconds=30,
        )
        cls.app = create_app(settings)
        cls.client_context = TestClient(cls.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def setUp(self):
        with self.app.state.session_factory() as session:
            session.execute(delete(ControlAction))
            session.execute(delete(TelemetrySample))
            session.commit()

    def _listener(self, hold_seconds):
        settings = replace(self.app.state.settings, auto_load_off=True, waste_hold_seconds=hold_seconds)
        listener = TelemetryListener(settings, self.app.state.session_factory, self.app.state.status)
        broker = Mock()
        broker.is_connected.return_value = True
        broker.publish.return_value.rc = 0
        listener._client = broker
        return listener, broker

    def _receive(self, listener, broker, body, topic=TOPIC, retain=False):
        listener._on_message(broker, None, SimpleNamespace(
            topic=topic, payload=json.dumps(body).encode(), retain=retain,
        ))

    def test_hold_timer_starts_and_cancels_on_occupancy(self):
        listener, broker = self._listener(30)
        self._receive(listener, broker, _payload(sequence=1, uptime_ms=2000))
        action = self.client.get("/rooms/room-1/control-actions").json()["actions"][0]
        self.assertEqual(action["status"], "watching")
        broker.publish.assert_not_called()
        self._receive(listener, broker, _payload(
            sequence=2, uptime_ms=4000, occupied=True, unoccupied_power_alert=False,
        ))
        action = self.client.get("/rooms/room-1/control-actions").json()["actions"][0]
        self.assertEqual(action["status"], "cancelled")
        broker.publish.assert_not_called()

    def test_hold_timer_cancels_when_load_turns_off(self):
        listener, broker = self._listener(30)
        self._receive(listener, broker, _payload(sequence=1, uptime_ms=2000))
        self._receive(listener, broker, _payload(
            sequence=2, uptime_ms=4000, light_on=False, power_w=0, unoccupied_power_alert=False,
        ))
        action = self.client.get("/rooms/room-1/control-actions").json()["actions"][0]
        self.assertEqual(action["status"], "cancelled")
        broker.publish.assert_not_called()

    def test_thirty_and_sixty_second_holds_send_off_once(self):
        for hold in (30, 60):
            with self.subTest(hold=hold):
                with self.app.state.session_factory() as session:
                    session.execute(delete(ControlAction))
                    session.execute(delete(TelemetrySample))
                    session.commit()
                listener, broker = self._listener(hold)
                self._receive(listener, broker, _payload(sequence=1, uptime_ms=2000))
                action = self.client.get("/rooms/room-1/control-actions").json()["actions"][0]
                self.assertEqual(action["status"], "watching")
                broker.publish.assert_not_called()
                with self.app.state.session_factory.begin() as session:
                    row = session.get(ControlAction, action["command_id"])
                    row.waste_started_at = datetime.now(timezone.utc) - timedelta(seconds=hold + 1)
                self._receive(listener, broker, _payload(sequence=2, uptime_ms=4000))
                self.assertEqual(broker.publish.call_count, 1)
                command = json.loads(broker.publish.call_args.args[1])
                self.assertEqual((command["target"], command["action"]), ("light", "off"))
                self._receive(listener, broker, _payload(sequence=3, uptime_ms=6000))
                self.assertEqual(broker.publish.call_count, 1)

    def test_confirmed_event_computes_savings_and_analytics(self):
        listener, broker = self._listener(0)
        prefix = TOPIC.rsplit("/", 1)[0]
        self._receive(listener, broker, _payload(sequence=1, uptime_ms=2000, power_w=20))
        command = json.loads(broker.publish.call_args.args[1])
        with self.app.state.session_factory.begin() as session:
            action = session.get(ControlAction, command["command_id"])
            action.waste_started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        self._receive(listener, broker, {
            "schema_version": 1, "message_type": "command_result", "device_id": "room-1",
            "command_id": command["command_id"], "accepted": True, "light_on": False,
            "fan_on": False, "ac_on": False, "uptime_ms": 2500,
        }, topic=prefix + "/state")
        self._receive(listener, broker, _payload(
            sequence=2, uptime_ms=4000, light_on=False, power_w=0, unoccupied_power_alert=False,
        ))
        event = self.client.get(f"/rooms/room-1/waste-events/{command['command_id']}").json()
        self.assertEqual(event["status"], "confirmed")
        self.assertGreater(event["energy_saved_wh"], 0)
        self.assertAlmostEqual(event["money_saved_inr"], event["energy_saved_kwh"] * 8, places=6)
        savings = self.client.get("/rooms/room-1/savings").json()
        self.assertEqual(savings["successful_corrections"], 1)
        analytics = self.client.get("/rooms/room-1/analytics").json()
        self.assertEqual(analytics["savings"]["successful_corrections"], 1)
        empty = self.client.get("/rooms/room-1/waste-events?since=2099-01-01T00:00:00Z")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["count"], 0)

    def test_old_telemetry_and_missing_ack_do_not_confirm(self):
        listener, broker = self._listener(0)
        self._receive(listener, broker, _payload(sequence=5, uptime_ms=10000))
        command = json.loads(broker.publish.call_args.args[1])
        self._receive(listener, broker, _payload(
            sequence=6, uptime_ms=12000, light_on=False, power_w=0, unoccupied_power_alert=False,
        ))
        self.assertEqual(self.client.get("/rooms/room-1/control-actions").json()["actions"][0]["status"], "pending")
        self._receive(listener, broker, {
            "schema_version": 1, "message_type": "command_result", "device_id": "room-1",
            "command_id": command["command_id"], "accepted": True, "light_on": False, "uptime_ms": 11000,
        }, topic=TOPIC.rsplit("/", 1)[0] + "/state", retain=True)
        self.assertEqual(self.client.get("/rooms/room-1/control-actions").json()["actions"][0]["status"], "pending")

    def test_manual_command_blocks_climate_on_when_dht_invalid(self):
        listener, broker = self._listener(0)
        self.app.state.listener = listener
        self.addCleanup(setattr, self.app.state, "listener", None)
        self._receive(listener, broker, _payload(
            sequence=1, uptime_ms=2000, occupied=True, light_on=False, dht_valid=False,
            temperature_c=None, humidity_percent=None, unoccupied_power_alert=False, power_w=0,
        ))
        blocked = self.client.post("/rooms/room-1/commands", json={"target": "fan", "action": "on"})
        self.assertEqual(blocked.status_code, 409)
        ok = self.client.post("/rooms/room-1/commands", json={"target": "light", "action": "on"})
        self.assertEqual(ok.status_code, 202)


if __name__ == "__main__":
    unittest.main()
