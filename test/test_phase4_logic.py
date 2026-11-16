import unittest

from sqlalchemy.exc import OperationalError

from phase4.energy import energy_interval
from phase4.ingest import ingest_message


TOPIC = "smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/telemetry"


class EnergyIntervalTests(unittest.TestCase):
    def test_first_sample_keeps_the_device_counter(self):
        interval = energy_interval(None, None, None, None, 10.0, 0.08, 1, 2000)
        self.assertEqual(interval.energy_delta_wh, 10.0)
        self.assertEqual(interval.cost_delta_inr, 0.08)
        self.assertFalse(interval.device_counter_reset)

    def test_later_sample_adds_only_the_increase(self):
        interval = energy_interval(10.0, 0.08, 1, 2000, 15.0, 0.12, 2, 4000)
        self.assertAlmostEqual(interval.energy_delta_wh, 5.0)
        self.assertAlmostEqual(interval.cost_delta_inr, 0.04)
        self.assertFalse(interval.device_counter_reset)

    def test_energy_drop_counts_as_a_new_boot(self):
        interval = energy_interval(15.0, 0.12, 8, 16000, 1.0, 0.008, 1, 2000)
        self.assertEqual(interval.energy_delta_wh, 1.0)
        self.assertEqual(interval.cost_delta_inr, 0.008)
        self.assertTrue(interval.device_counter_reset)

    def test_higher_energy_adds_only_the_increase(self):
        # Sequence can go backwards when an older message arrives late.
        # The server adds the increase only. A real reboot shows a lower counter.
        interval = energy_interval(15.0, 0.12, 40, 80000, 50.0, 0.40, 20, 40000)
        self.assertAlmostEqual(interval.energy_delta_wh, 35.0)
        self.assertAlmostEqual(interval.cost_delta_inr, 0.28)
        self.assertFalse(interval.device_counter_reset)

    def test_same_reading_adds_nothing(self):
        interval = energy_interval(15.0, 0.12, 2, 4000, 15.0, 0.12, 3, 6000)
        self.assertEqual(interval.energy_delta_wh, 0.0)
        self.assertEqual(interval.cost_delta_inr, 0.0)
        self.assertFalse(interval.device_counter_reset)


class IngestFailureTests(unittest.TestCase):
    def test_invalid_message_is_rejected_without_touching_the_database(self):
        def session_factory():
            raise AssertionError("invalid telemetry must not open a database session")

        outcome = ingest_message(TOPIC, b"{bad", session_factory)
        self.assertEqual(outcome["status"], "rejected")

    def test_database_error_is_reported_and_contained(self):
        def session_factory():
            raise OperationalError("INSERT", {}, Exception("connection refused"))

        outcome = ingest_message(TOPIC, _payload(sequence=1), session_factory)
        self.assertEqual(outcome["status"], "database_error")
        self.assertEqual(outcome["reason"], "database write failed")


def _payload(sequence):
    return {
        "schema_version": 1,
        "message_type": "telemetry",
        "device_id": "room-1",
        "firmware_version": "3.0.0",
        "sequence": sequence,
        "uptime_ms": sequence * 2000,
        "occupied": True,
        "ldr_raw": 1000,
        "is_dark": False,
        "temperature_c": 30.0,
        "humidity_percent": 50.0,
        "dht_valid": True,
        "light_on": False,
        "fan_on": True,
        "ac_on": False,
        "control_mode": "automatic",
        "current_sensor_raw": 0,
        "power_sensor_valid": True,
        "voltage_v": 230.0,
        "sensor_current_a": 0.0,
        "current_a": 0.326,
        "load_model_power_w": 75.0,
        "power_w": 75.0,
        "energy_wh": 1.0,
        "energy_kwh": 0.001,
        "estimated_cost_inr": 0.008,
        "high_power_alert": False,
        "unoccupied_power_alert": False,
    }


if __name__ == "__main__":
    unittest.main()
