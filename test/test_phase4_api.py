import os
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import SQLAlchemyError

from phase4.config import Settings
from phase4.ingest import ingest_message
from phase4.main import create_app
from phase4.models import TelemetrySample


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
        "occupied": True,
        "ldr_raw": 2200,
        "is_dark": True,
        "temperature_c": 30.5,
        "humidity_percent": 55.0,
        "dht_valid": True,
        "light_on": True,
        "fan_on": True,
        "ac_on": False,
        "control_mode": "automatic",
        "current_sensor_raw": 0,
        "power_sensor_valid": True,
        "voltage_v": 230.0,
        "sensor_current_a": 0.0,
        "current_a": 0.413,
        "load_model_power_w": 95.0,
        "power_w": 95.0,
        "energy_wh": 0.0,
        "energy_kwh": 0.0,
        "estimated_cost_inr": 0.0,
        "high_power_alert": False,
        "unoccupied_power_alert": False,
    }
    body.update(overrides)
    return body


@unittest.skipUnless(_database_is_reachable(), "PostgreSQL test database is not running")
class Phase4ApiTests(unittest.TestCase):
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
        )
        cls.app = create_app(settings)
        cls.client_context = TestClient(cls.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def setUp(self):
        factory = self.app.state.session_factory
        with factory() as session:
            session.execute(delete(TelemetrySample))
            session.commit()

    def test_health_reports_database_without_starting_mqtt(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["database"], "ok")
        self.assertFalse(body["mqtt_enabled"])
        self.assertTrue(body["current_is_simulated"])

    def test_missing_room_returns_404_and_bad_id_returns_400(self):
        missing = self.client.get("/rooms/room-1")
        self.assertEqual(missing.status_code, 404)
        bad_id = self.client.get("/rooms/room 1")
        self.assertEqual(bad_id.status_code, 400)

    def test_history_survives_a_device_counter_reset(self):
        self._store(_payload(sequence=1, uptime_ms=2000, energy_wh=10.0, energy_kwh=0.01, estimated_cost_inr=0.08))
        self._store(_payload(sequence=2, uptime_ms=4000, energy_wh=15.0, energy_kwh=0.015, estimated_cost_inr=0.12))
        reboot = self._store(
            _payload(sequence=1, uptime_ms=2000, energy_wh=1.0, energy_kwh=0.001, estimated_cost_inr=0.008)
        )
        self.assertEqual(reboot["status"], "stored")
        self.assertTrue(reboot["device_counter_reset"])

        # Replaying the second sample must not increase the server total.
        duplicate = self._store(
            _payload(sequence=2, uptime_ms=4000, energy_wh=15.0, energy_kwh=0.015, estimated_cost_inr=0.12)
        )
        self.assertEqual(duplicate["status"], "duplicate")

        rejected = ingest_message(TOPIC, b"not-json", self.app.state.session_factory)
        self.assertEqual(rejected["status"], "rejected")

        energy = self.client.get("/rooms/room-1/energy")
        self.assertEqual(energy.status_code, 200)
        bill = energy.json()
        self.assertEqual(bill["sample_count"], 3)
        self.assertEqual(bill["device_counter_resets"], 1)
        self.assertAlmostEqual(bill["server_energy_wh"], 16.0)
        self.assertAlmostEqual(bill["server_cost_inr"], 0.128)
        self.assertAlmostEqual(bill["latest_device_energy_wh"], 1.0)
        self.assertTrue(bill["current_is_simulated"])

        history = self.client.get("/rooms/room-1/telemetry?limit=10")
        self.assertEqual(history.status_code, 200)
        samples = history.json()["samples"]
        self.assertEqual(len(samples), 3)
        self.assertEqual(samples[0]["sequence"], 1)
        self.assertEqual(samples[0]["energy_wh"], 1.0)
        self.assertTrue(samples[0]["device_counter_reset"])
        self.assertEqual(samples[0]["light_on"], True)
        self.assertEqual(samples[0]["control_mode"], "automatic")

        rooms = self.client.get("/rooms")
        self.assertEqual(rooms.status_code, 200)
        self.assertEqual(rooms.json()["rooms"][0]["device_id"], "room-1")
        self.assertAlmostEqual(rooms.json()["rooms"][0]["server_energy_wh"], 16.0)

    def test_later_message_with_lower_sequence_does_not_double_count(self):
        self._store(_payload(sequence=40, uptime_ms=80000, energy_wh=15.0, energy_kwh=0.015, estimated_cost_inr=0.12))
        later = self._store(
            _payload(sequence=20, uptime_ms=40000, energy_wh=50.0, energy_kwh=0.05, estimated_cost_inr=0.40)
        )
        self.assertFalse(later["device_counter_reset"])
        bill = self.client.get("/rooms/room-1/energy").json()
        self.assertAlmostEqual(bill["server_energy_wh"], 50.0)
        self.assertAlmostEqual(bill["latest_device_energy_wh"], 50.0)

    def test_alert_endpoint_returns_only_flagged_samples(self):
        self._store(_payload(sequence=1, uptime_ms=2000, power_w=95.0))
        self._store(
            _payload(
                sequence=2,
                uptime_ms=4000,
                occupied=True,
                power_w=1900.0,
                high_power_alert=True,
                energy_wh=2.0,
                energy_kwh=0.002,
                estimated_cost_inr=0.016,
            )
        )
        self._store(
            _payload(
                sequence=3,
                uptime_ms=6000,
                occupied=False,
                light_on=False,
                fan_on=False,
                power_w=20.0,
                unoccupied_power_alert=True,
                energy_wh=3.0,
                energy_kwh=0.003,
                estimated_cost_inr=0.024,
            )
        )
        response = self.client.get("/rooms/room-1/alerts?limit=10")
        self.assertEqual(response.status_code, 200)
        alerts = response.json()["alerts"]
        self.assertEqual(len(alerts), 2)
        self.assertTrue(alerts[0]["unoccupied_power_alert"])
        self.assertTrue(alerts[1]["high_power_alert"])

    def _store(self, payload):
        outcome = ingest_message(TOPIC, payload, self.app.state.session_factory)
        self.assertIn(outcome["status"], {"stored", "duplicate"})
        return outcome


if __name__ == "__main__":
    unittest.main()
