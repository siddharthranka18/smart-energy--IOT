# IoT-Based Intelligent Energy Management System

An embedded IoT energy management and climate automation prototype designed for academic engineering demonstration. The system dynamically controls simulated lighting and multi-stage cooling appliances based on physical room occupancy, ambient lux/illumination levels, and temperature thresholds to minimize idle power waste, while providing cloud-connected MQTT telemetry and remote manual control.

---

## 📌 Phase 1 & 2 System Architecture

The architecture bridges edge sensor automation with cloud telemetry and control:

```
[Sensors: PIR / LDR / DHT22]
            │
            ▼
    [ESP32 Microcontroller]  ◄─── (Wokwi-GUEST Wi-Fi) ───►  [MQTT Broker: HiveMQ]
    - Local Deterministic Rules                                    │
    - Non-blocking Millis Loop                                     │
    - Manual Override State Machine                                │
            │                                                      ▼
            │ (GPIO Outputs)                             [Subscribers & Control]
            ▼                                            - Telemetry Stream
    [Actuator LEDs: Light, Fan, AC]                      - Remote Override Commands
```

### Subsystem Specifications
- **Microcontroller**: Espressif ESP32 Dev Module (Wokwi virtual & physical hardware)
- **Occupancy Subsystem**: Digital PIR Motion Sensor (`wokwi-pir-motion-sensor`) on GPIO 14
- **Lighting Subsystem**: Analog LDR Photoresistor (`wokwi-photoresistor-sensor`) on GPIO 34 & Room Light LED on GPIO 2
- **Climate Subsystem**: DHT22 Temp & Humidity (`wokwi-dht22`) on GPIO 15, Fan LED on GPIO 4, AC LED on GPIO 5
- **Connectivity**: IEEE 802.11b/g/n Wi-Fi (`Wokwi-GUEST`) + MQTT v3.1.1 (`PubSubClient` + `ArduinoJson`)
- **Telemetry Period**: 2000 ms periodic non-blocking sampling cycle

---

## 🔌 Hardware Pin Mapping & Circuit Layout

| Peripheral / Component | Wokwi Part Type | Component Pin | ESP32 GPIO | Mode | Signal / Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Room Light Indicator** | `wokwi-led` (Yellow) | Anode (A) / Cathode via 220Ω to GND | **GPIO 2** | `OUTPUT` | Simulated Lighting Load |
| **Fan Indicator** | `wokwi-led` (Blue) | Anode (A) / Cathode via 220Ω to GND | **GPIO 4** | `OUTPUT` | Simulated Ventilation Load |
| **AC Indicator** | `wokwi-led` (Orange) | Anode (A) / Cathode via 220Ω to GND | **GPIO 5** | `OUTPUT` | Simulated Refrigeration Load |
| **PIR Motion Sensor** | `wokwi-pir-motion-sensor` | `OUT` (`VCC`=5V, `GND`=GND) | **GPIO 14** | `INPUT` | Digital Occupancy (HIGH = Motion) |
| **DHT22 Sensor** | `wokwi-dht22` | `SDA` (`VCC`=3V3, `GND`=GND) | **GPIO 15** | `INPUT_PULLUP` | Single-wire Temp/RH Bus |
| **LDR Sensor Module** | `wokwi-photoresistor-sensor` | `AO` (`VCC`=3V3, `GND`=GND) | **GPIO 34** | `INPUT` | Analog Illumination (ADC1_CH6) |

---

## ⚙️ Control Matrix & Priority Logic

```
                   +----------------------------------+
                   |         Sensor Sampling          |
                   |  PIR (GPIO 14), LDR (GPIO 34),   |
                   |  DHT22 Temp & Humidity (GPIO 15) |
                   +----------------+-----------------+
                                    |
                                    v
                            [Is Room Occupied?]
                               /          \
                         NO   /            \   YES
                             v              v
                   +----------------+   +------------------------------------+
                   | All Loads OFF  |   | 1. Light: ON if Dark (ADC >= 2000) |
                   | Light = OFF    |   | 2. Fan  : ON if Temp >= 28.0°C     |
                   | Fan   = OFF    |   | 3. AC   : ON if Temp >= 32.0°C     |
                   | AC    = OFF    |   | Failsafe: DHT NaN -> Fan & AC OFF  |
                   +----------------+   +------------------------------------+
                                    │
                                    v
                     [Phase 2 Manual Override Active?]
                               /          \
                         NO   /            \   YES
                             v              v
                  [Apply Automatic State]   [Apply Commanded State with Timer Expiry]
                                            (DHT Failsafe Still Guards Climate Loads)
```

1. **Rule 1 (Occupancy Override)**: If `occupied == false`, all simulated loads (Light, Fan, AC) are immediately turned **OFF** to eliminate phantom draw.
2. **Rule 2 (Smart Lighting)**: If occupied and ambient light is below threshold (`rawLdr >= LDR_DARK_THRESHOLD`, 2000 ADC), Room Light LED turns **ON**; otherwise **OFF**.
3. **Rule 3 (Stage 1 Cooling / Fan)**: If occupied and temperature $\ge 28.0^\circ\text{C}$, Fan LED turns **ON**; otherwise **OFF**.
4. **Rule 4 (Stage 2 Cooling / AC)**: If occupied and temperature $\ge 32.0^\circ\text{C}$, AC LED turns **ON**; otherwise **OFF**.
5. **DHT Failsafe**: If DHT22 reads `NaN`, climate loads (Fan and AC) default safely to **OFF**.
6. **Manual Override Precedence**: Valid MQTT commands temporarily supersede automatic rules for a configurable duration (`expires_in_seconds`, default 60s). When the timer expires, the node seamlessly resumes automatic control.

---

## 🌐 Phase 2 MQTT Communication Architecture

### Network Parameters
- **Wi-Fi SSID**: `Wokwi-GUEST` (open network, channel 6)
- **MQTT Broker**: `broker.hivemq.com` (public demo broker, port 1883)
- **Device ID**: `room-1`
- **Topic Prefix**: `smart-energy-demo/iot-energy-mgmt`
- **Client ID**: `iot-energy-room-1-<CHIP_ID>` (derived from ESP32 MAC address)

> [!CAUTION]
> The demonstration uses unencrypted TCP port 1883 on a public test broker without authentication. This is intended for academic simulation. Production IoT deployments must use TLS (port 8883) and mutual authentication certificates.

### Topic Structure
| Topic | Direction | Retained | Purpose |
| :--- | :--- | :--- | :--- |
| `smart-energy-demo/iot-energy-mgmt/room-1/telemetry` | ESP32 ➔ Broker | `false` | Full telemetry payload every 2 seconds |
| `smart-energy-demo/iot-energy-mgmt/room-1/state` | ESP32 ➔ Broker | `false` | Command result acknowledgements |
| `smart-energy-demo/iot-energy-mgmt/room-1/command` | Broker ➔ ESP32 | `false` | Remote control command ingestion |
| `smart-energy-demo/iot-energy-mgmt/room-1/status` | ESP32 ➔ Broker | `true` | Node presence beacon (`online`) / LWT (`offline`) |

---

## 📦 JSON Message Formats

### 1. Periodic Telemetry (`.../telemetry`)
```json
{
  "schema_version": 1,
  "message_type": "telemetry",
  "device_id": "room-1",
  "sequence": 14,
  "uptime_ms": 28000,
  "occupied": true,
  "ldr_raw": 2850,
  "is_dark": true,
  "temperature_c": 30.5,
  "humidity_percent": 55.0,
  "dht_valid": true,
  "light_on": true,
  "fan_on": true,
  "ac_on": false,
  "control_mode": "automatic"
}
```
*Note: In the event of a DHT22 sensor read failure, `temperature_c` and `humidity_percent` are serialized as JSON `null` (never invalid `NaN`), and `dht_valid` is set to `false`.*

### 2. Inbound Remote Command (`.../command`)
```json
{
  "schema_version": 1,
  "command_id": "cmd-001",
  "device_id": "room-1",
  "target": "light",
  "action": "off",
  "mode": "manual",
  "expires_in_seconds": 60
}
```
- Supported targets: `light`, `fan`, `ac`, `all`, `automatic`
- Supported actions: `on`, `off`
- Target `automatic` immediately cancels overrides and restores sensor control.
- Target `all` with action `off` disables all loads.

### 3. Command Result Acknowledgement (`.../state`)
```json
{
  "schema_version": 1,
  "message_type": "command_result",
  "device_id": "room-1",
  "command_id": "cmd-001",
  "accepted": true,
  "reason": "command_applied",
  "control_mode": "manual_override",
  "light_on": false,
  "fan_on": true,
  "ac_on": false,
  "uptime_ms": 28500
}
```

---

## 🚀 Quick Start Guide

### 1. Build Firmware
```powershell
.\build.bat
```
*(Uses PlatformIO CLI to compile `src/main.cpp` and produce `.pio\build\esp32dev\firmware.bin`)*

### 2. Run Automated Verification Test Suites
```powershell
.\verify.bat
```
Executes both test suites offline with GCC/MinGW:
- **Phase 1 Suite**: 12/12 unit tests passing (deterministic local rules, edge cases, failsafes)
- **Phase 2 Suite**: 51/51 assertions passing (command parsing, payload normalization, override timer, safety fallbacks)

### 3. Run Simulation in Wokwi
1. Open [`diagram.json`](diagram.json) in VS Code.
2. Click the green **Play** button.
3. Open the Serial Monitor at **115200 baud** to view real-time cycle telemetry.

### 4. Remote Interaction via Mosquitto CLI / MQTT Explorer

#### Subscribe to Live Telemetry:
```powershell
mosquitto_sub -h broker.hivemq.com -p 1883 -t "smart-energy-demo/iot-energy-mgmt/room-1/#" -v
```

#### Send Test Command (Turn Light OFF for 30s):
**Windows PowerShell (using pipeline):**
```powershell
'{"schema_version":1,"command_id":"cmd-001","device_id":"room-1","target":"light","action":"off","mode":"manual","expires_in_seconds":30}' | mosquitto_pub -h broker.hivemq.com -p 1883 -t "smart-energy-demo/iot-energy-mgmt/room-1/command" -l
```

**Linux / macOS / Git Bash:**
```bash
mosquitto_pub -h broker.hivemq.com -p 1883 -t "smart-energy-demo/iot-energy-mgmt/room-1/command" -m '{"schema_version":1,"command_id":"cmd-001","device_id":"room-1","target":"light","action":"off","mode":"manual","expires_in_seconds":30}'
```

*(Note: The firmware includes built-in payload normalization that automatically unescapes `\"` and strips wrapper quotes, so commands sent via any shell or MQTT tool are parsed reliably.)*

---

## 📋 Project Roadmap & Status

- [x] **Phase 1**: Embedded sensor acquisition & deterministic local load control
- [x] **Phase 1**: Wokwi simulated circuit (PIR, LDR, DHT22, LEDs) & 12-case unit tests
- [x] **Phase 2**: ESP32 Wi-Fi connectivity (`Wokwi-GUEST`) with non-blocking reconnection
- [x] **Phase 2**: MQTT telemetry publication, command ingestion, and state acknowledgements
- [x] **Phase 2**: Time-bounded manual override with automatic fallback and DHT safety enforcement
- [x] **Phase 2**: Phase 2 logic verification test suite (51/51 assertions passing)
- [ ] **Phase 3**: Telemetry ingestion service & physical energy metering (voltage/current sensors)
- [ ] **Phase 4**: Python backend (FastAPI) and PostgreSQL database
- [ ] **Phase 5**: Web monitoring and control dashboard (React / Vite)
