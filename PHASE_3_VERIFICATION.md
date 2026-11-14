# Phase 3 Energy Measurement & Telemetry Ingestion

Phase 3 extends the working Phase 2 MQTT node with simulated electrical measurement, accumulated energy and cost, energy-waste alerts, and a broker-side Python ingestion service. Phase 1 and Phase 2 behavior remains intact.

## Implemented flow

```text
PIR / LDR / DHT22 / Current Potentiometer
                    ↓
         ESP32 automatic control
                    ↓
      Power + energy + cost calculation
                    ↓
             MQTT telemetry
                    ↓
      Python validation and alert rules
                    ↓
      Structured console / optional JSONL
```

## Electrical simulation

- Supply voltage: `230 V`
- Light rating: `20 W`
- Fan rating: `75 W`
- AC rating: `1500 W`
- GPIO 35 potentiometer range: `0–10 A`
- Tariff: `INR 8.00/kWh`
- High-power threshold: `1800 W`
- Unoccupied-power threshold: `10 W`

The active appliance ratings form the modeled power. The potentiometer forms a simulated sensor measurement. The firmware uses the larger value:

```text
modeled_power = active load ratings added together
sensor_power  = 230 × simulated_current
power_w       = max(modeled_power, sensor_power)
energy_wh    += power_w × elapsed_ms / 3,600,000
cost_inr      = energy_kwh × 8.00
```

Using unsigned elapsed-time subtraction keeps energy accumulation correct across `millis()` rollover. Energy and cost reset when the ESP32 reboots; persistent storage belongs to Phase 4.

## MQTT topics

```text
smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/telemetry
smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/alert
smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/command
smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/state
smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/status
```

The ingestion service subscribes to the multi-room wildcard:

```text
smart-energy-demo/siddharthranka18-smart-energy-2026/+/telemetry
```

## Phase 3 telemetry fields

The original sensor and actuator fields remain. These fields are added:

```json
{
  "firmware_version": "3.0.0",
  "current_sensor_raw": 0,
  "power_sensor_valid": true,
  "voltage_v": 230.0,
  "sensor_current_a": 0.0,
  "current_a": 0.413,
  "load_model_power_w": 95.0,
  "power_w": 95.0,
  "energy_wh": 12.45,
  "energy_kwh": 0.01245,
  "estimated_cost_inr": 0.0996,
  "high_power_alert": false,
  "unoccupied_power_alert": false
}
```

Alert messages are published only when an alert becomes active or clears:

```json
{
  "schema_version": 1,
  "message_type": "energy_alert",
  "device_id": "room-1",
  "firmware_version": "3.0.0",
  "alert_code": "power_in_unoccupied_room",
  "active": true,
  "severity": "warning",
  "power_w": 1150.3,
  "uptime_ms": 25000
}
```

## Automated verification

Run:

```powershell
.\verify.bat
```

Expected results:

- Phase 1: `12/12`
- Phase 2: `63/63`
- Phase 3 C++: `20/20`
- Phase 3 Python ingestion: `12/12`

Build the ESP32 firmware:

```powershell
.\build.bat
```

## Wokwi verification

1. Close any already-open Wokwi Simulator tab after rebuilding, so cached firmware is not reused.
2. Open `diagram.json` and start **Wokwi: Start Simulator**.
3. Confirm the serial banner says `Phase 3`.
4. Confirm telemetry contains `firmware_version: 3.0.0`, `power_w`, `energy_wh`, and `estimated_cost_inr`.
5. With the potentiometer at zero, power follows the active light/fan/AC model.
6. Raise the potentiometer to simulate additional current. At full scale, telemetry approaches `10 A` and `2300 W`.
7. With the room unoccupied and simulated power above `10 W`, confirm `power_in_unoccupied_room` becomes active.
8. At `1800 W` or above, confirm `high_power_consumption` becomes active.

## Run the ingestion service

```powershell
python -m pip install -r requirements-phase3.txt
python -m phase3.ingestion_service
```

Optional environment configuration:

```powershell
$env:MQTT_BROKER = "broker.hivemq.com"
$env:MQTT_PORT = "1883"
$env:TELEMETRY_LOG_PATH = "logs/telemetry.jsonl"
python -m phase3.ingestion_service
```

The service validates schema, field types and ranges, topic/device consistency, DHT null handling, and multi-room topics. Invalid messages are logged as `telemetry_rejected`; valid messages receive a UTC `received_at` timestamp.

## Phase boundary

Phase 3 does not add PostgreSQL, FastAPI REST endpoints, user accounts, or a web dashboard. The public broker on port 1883 remains demonstration-only. Database persistence and backend APIs belong to Phase 4.
