# Phase 4 FastAPI Backend and PostgreSQL

Phase 4 stores the telemetry that the ESP32 already publishes. The firmware, MQTT topics, and Phase 3 console ingestion service are unchanged. Current and power are still the simulated values from the firmware, not readings from a physical meter.

```text
ESP32 in Wokwi
    |
    | MQTT telemetry every 2 seconds
    v
broker.hivemq.com:1883
    |
    v
Phase 4 listener  --validate with phase3.telemetry_core-->  PostgreSQL
    |
    v
FastAPI  /rooms  /telemetry  /energy  /alerts
```

The ESP32 energy and cost counters return to zero on reboot. Each stored row keeps the device counters as published, plus the interval added to the server total. The server total is the sum of those intervals, so older history remains after a restart.

## Database

Local demo connection:

```text
postgresql+psycopg://energy:energy@127.0.0.1:5432/smart_energy
```

One table, `telemetry_samples`, holds the history. `create_all` creates it on startup. The columns are the firmware telemetry fields, the server receive time, and three bookkeeping fields:

| Column | Meaning |
| :--- | :--- |
| `received_at` | UTC time the backend accepted the message |
| `device_id`, `firmware_version`, `sequence`, `uptime_ms` | Identity and device clock from the payload |
| `occupied`, `ldr_raw`, `is_dark`, `temperature_c`, `humidity_percent`, `dht_valid` | Sensor readings. Temperature and humidity are null when DHT data is invalid |
| `light_on`, `fan_on`, `ac_on`, `control_mode` | Load state and `automatic` or `manual_override` |
| `current_sensor_raw`, `sensor_current_a`, `current_a`, `voltage_v` | Simulated current channel and the fixed voltage sent by the firmware |
| `load_model_power_w`, `power_w`, `power_sensor_valid` | Simulated power |
| `energy_wh`, `energy_kwh`, `estimated_cost_inr` | Device counters. These reset when the ESP32 restarts |
| `high_power_alert`, `unoccupied_power_alert` | Alert flags from the firmware |
| `energy_delta_wh`, `cost_delta_inr` | Amount this row adds to the server total |
| `device_counter_reset` | True when the device energy counter fell. That is how a reboot is recognized |

A repeated sample with the same device, sequence, uptime, and energy is ignored so a broker replay does not inflate the total.

## Install PostgreSQL

Docker is optional. From the project folder, if Docker is installed:

```powershell
docker compose up -d
```

Without Docker, install PostgreSQL 16 for Windows. This project machine already has PostgreSQL 16 running as the Windows service `smart-energy-postgres`. The installer superuser is `postgres` with password `energy`. Create the application login in psql:

```sql
CREATE USER energy WITH PASSWORD 'energy';
CREATE DATABASE smart_energy OWNER energy;
CREATE DATABASE smart_energy_test OWNER energy;
```

The second database is only for the automated API tests.

## Run the backend

```powershell
py -m pip install -r requirements-phase4.txt
copy .env.example .env
py -m phase4
```

Leave that window open. The API is `http://127.0.0.1:8000` and the interactive page is `http://127.0.0.1:8000/docs`.

Check the process before starting Wokwi:

```powershell
py -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

`database` should be `ok`. `mqtt_connected` becomes true after the broker accepts the subscription.

## API examples

```powershell
py -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/rooms').read().decode())"
py -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/rooms/room-1').read().decode())"
py -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/rooms/room-1/telemetry?limit=10').read().decode())"
py -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/rooms/room-1/energy').read().decode())"
py -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/rooms/room-1/alerts?limit=10').read().decode())"
```

| Method and path | Result |
| :--- | :--- |
| `GET /health` | Database and MQTT status |
| `GET /rooms` | Rooms that have stored samples. This project publishes `room-1` |
| `GET /rooms/room-1` | Latest stored reading |
| `GET /rooms/room-1/telemetry?limit=50` | Newest history first. `limit` is 1 to 500 |
| `GET /rooms/room-1/energy` | Server energy and cost, plus the latest device counters |
| `GET /rooms/room-1/alerts?limit=20` | Samples whose high-power or empty-room flag is true |

An unknown room returns 404. A database outage returns 503 on the data routes and `degraded` on `/health`. Invalid MQTT payloads are logged and are not inserted.

## Wokwi check

1. Start PostgreSQL, then `py -m phase4`.
2. Start the Wokwi simulation and wait for `[MQTT] Telemetry #1 publish SUCCESS` in the serial monitor.
3. Open `http://127.0.0.1:8000/rooms/room-1/energy`.
4. `sample_count` increases about every 2 seconds. `server_energy_wh` increases while a load is on or the current potentiometer is above zero.
5. Stop the simulation and refresh the energy URL. The stored samples are still there.
6. Start the simulation again. The device counters start over, and the new row is marked `device_counter_reset`. `server_energy_wh` keeps the old total and continues from it.

## Automated tests

```powershell
.\verify.bat
```

Phase 4 logic tests always run. The PostgreSQL API tests run when `smart_energy_test` is reachable. To point them at another database:

```powershell
$env:PHASE4_TEST_DATABASE_URL = "postgresql+psycopg://energy:energy@127.0.0.1:5432/smart_energy_test"
py -m unittest -v test.test_phase4_logic test.test_phase4_api
```

## Limits

- The only firmware node is `room-1`. The API can read whatever device id was stored, but no second node is part of this phase.
- There is no login and no web dashboard. The dashboard is Phase 5.
- The public MQTT broker on port 1883 is still an unencrypted demonstration broker.
- Server totals cannot include samples that were never received. They do keep every sample that was stored.
- A reboot is recognized when the stored device energy counter falls. If the backend misses the whole reboot and the new counter is already higher than the last stored value, the server adds only the increase it can see.
