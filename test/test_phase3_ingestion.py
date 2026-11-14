import json
import unittest

from phase3.telemetry_core import (
    TelemetryValidationError,
    build_ingestion_record,
    evaluate_alerts,
    validate_telemetry,
)


TOPIC = "smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/telemetry"


def valid_payload():
    return {
        "schema_version": 1,
        "message_type": "telemetry",
        "device_id": "room-1",
        "firmware_version": "3.0.0",
        "sequence": 1,
        "uptime_ms": 1000,
        "occupied": True,
        "ldr_raw": 1000,
        "is_dark": False,
        "temperature_c": 24.0,
        "humidity_percent": 40.0,
        "dht_valid": True,
        "light_on": False,
        "fan_on": False,
        "ac_on": False,
        "control_mode": "automatic",
        "current_sensor_raw": 0,
        "power_sensor_valid": True,
        "voltage_v": 230.0,
        "sensor_current_a": 0.0,
        "current_a": 0.0,
        "load_model_power_w": 0.0,
        "power_w": 0.0,
        "energy_wh": 0.0,
        "energy_kwh": 0.0,
        "estimated_cost_inr": 0.0,
        "high_power_alert": False,
        "unoccupied_power_alert": False,
    }


class Phase3IngestionTests(unittest.TestCase):
    def test_valid_json_is_accepted_and_timestamped(self):
        result = validate_telemetry(TOPIC, json.dumps(valid_payload()))
        self.assertEqual(result["device_id"], "room-1")
        self.assertIn("received_at", result)

    def test_bytes_payload_is_accepted(self):
        result = validate_telemetry(TOPIC, json.dumps(valid_payload()).encode())
        self.assertEqual(result["power_w"], 0.0)

    def test_multiple_room_topic_is_supported(self):
        payload = valid_payload()
        payload["device_id"] = "lab-2"
        result = validate_telemetry(
            "smart-energy-demo/siddharthranka18-smart-energy-2026/lab-2/telemetry", payload
        )
        self.assertEqual(result["device_id"], "lab-2")

    def test_topic_device_mismatch_is_rejected(self):
        with self.assertRaises(TelemetryValidationError):
            validate_telemetry(TOPIC, {**valid_payload(), "device_id": "room-2"})

    def test_malformed_json_is_rejected(self):
        with self.assertRaises(TelemetryValidationError):
            validate_telemetry(TOPIC, "{not-json}")

    def test_non_finite_power_is_rejected(self):
        payload = valid_payload()
        payload["power_w"] = float("nan")
        with self.assertRaises(TelemetryValidationError):
            validate_telemetry(TOPIC, payload)

    def test_invalid_sensor_range_is_rejected(self):
        payload = valid_payload()
        payload["current_sensor_raw"] = 5000
        with self.assertRaises(TelemetryValidationError):
            validate_telemetry(TOPIC, payload)

    def test_dht_null_is_allowed_when_invalid(self):
        payload = valid_payload()
        payload.update(dht_valid=False, temperature_c=None, humidity_percent=None)
        self.assertFalse(validate_telemetry(TOPIC, payload)["dht_valid"])

    def test_dht_null_is_rejected_when_marked_valid(self):
        payload = valid_payload()
        payload["temperature_c"] = None
        with self.assertRaises(TelemetryValidationError):
            validate_telemetry(TOPIC, payload)

    def test_high_power_alert_is_generated(self):
        payload = validate_telemetry(TOPIC, {**valid_payload(), "power_w": 2000.0})
        codes = {alert["alert_code"] for alert in evaluate_alerts(payload)}
        self.assertIn("high_power_consumption", codes)

    def test_unoccupied_power_alert_is_generated(self):
        payload = valid_payload()
        payload.update(occupied=False, power_w=20.0)
        codes = {alert["alert_code"] for alert in evaluate_alerts(validate_telemetry(TOPIC, payload))}
        self.assertIn("power_in_unoccupied_room", codes)

    def test_ingestion_record_contains_alerts(self):
        payload = valid_payload()
        payload.update(occupied=False, power_w=2300.0)
        record = build_ingestion_record(TOPIC, payload)
        self.assertEqual(record["event"], "telemetry_accepted")
        self.assertEqual(len(record["alerts"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
