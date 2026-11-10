# Phase 2 Implementation & Verification Guide

This document details the **Phase 2 Wi-Fi & MQTT implementation**, topic structures, JSON message contracts, verification procedures, and operational boundaries for the **IoT-Based Intelligent Energy Management System**.

---

## 📌 Phase 2 Scope & Objectives

Phase 2 extends the local automated energy controller into a networked IoT node:

```
[Sensors: PIR / LDR / DHT22] 
            │
            ▼
     [ESP32 Firmware] ──(Wi-Fi / MQTT)──► [MQTT Broker: HiveMQ]
            │                                    │
            │ (Local Relays / LEDs)              │ (Remote Commands)
            ▼                                    ▼
 [Loads: Light, Fan, AC] ◄───────────────────────┘
```

### Key Principles
1. **Local Automation Autonomy**: Local sensor reading and energy conservation rules run uninterrupted even if Wi-Fi or the MQTT broker is offline.
2. **Deterministic Precedence**: Valid remote commands temporarily override local rules (`manual_override` mode) for a bounded duration (`expires_in_seconds`), after which the system automatically reverts to `automatic` mode.
3. **Failsafe Supremacy**: If environmental sensors fail (DHT22 reading `NaN`), climate loads (Fan, AC) are forced safely to `OFF` even if an active manual override requests them `ON`.
4. **Standard JSON Compliance**: When DHT data is invalid, `temperature_c` and `humidity_percent` are serialized as JSON `null` (never invalid `NaN`).

---

## 🌐 Network & MQTT Broker Architecture

| Parameter | Configuration Setting | Details |
| :--- | :--- | :--- |
| **Wi-Fi SSID** | `Wokwi-GUEST` | Simulated virtual AP provided by Wokwi |
| **Wi-Fi Password** | `""` (Empty) | Open authentication |
| **Wi-Fi Channel** | `6` | Standard Wokwi network channel |
| **MQTT Broker** | `broker.hivemq.com` | Public demo non-TLS broker (Port 1883) |
| **Device Identifier** | `room-1` | Target room node |
| **MQTT Client ID** | `iot-energy-room-1-<CHIP_ID>` | Unique hex chip MAC suffix prevents collision |
| **Project Topic Prefix** | `smart-energy-demo/siddharthranka18-smart-energy-2026` | Project-unique namespace avoiding public broker clashes |

> [!CAUTION]
> Public MQTT on port 1883 is unencrypted and carries no authentication. It is intended solely for academic demonstration and simulation. Production deployments must use TLS (port 8883) and mutual authentication.

---

## 📡 Complete MQTT Topic Map

| Topic | Direction | Retained | QoS | Function / Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `.../room-1/telemetry` | ESP32 ➔ Broker | `false` | 0 | Sensor readings, actuator states, and uptime every 2 seconds |
| `.../room-1/state` | ESP32 ➔ Broker | `false` | 0 | Command execution results and acknowledgements |
| `.../room-1/command` | Broker ➔ ESP32 | `false` | 1 | Inbound remote control commands |
| `.../room-1/status` | ESP32 ➔ Broker | `true` | 0 | Node presence beacon (`online`) and Last Will & Testament (`offline`) |

Full topic prefix: `smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/`

---

## 📋 JSON Message Contracts

### 1. Telemetry Telemetry Payload (`.../telemetry`)
Published every 2 seconds.

```json
{
  "schema_version": 1,
  "message_type": "telemetry",
  "device_id": "room-1",
  "firmware_version": "2.1.0",
  "sequence": 42,
  "uptime_ms": 84000,
  "occupied": true,
  "ldr_raw": 2700,
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

*When DHT22 is in a fault or disconnected state:*
```json
{
  "schema_version": 1,
  "message_type": "telemetry",
  "device_id": "room-1",
  "firmware_version": "2.1.0",
  "sequence": 43,
  "uptime_ms": 86000,
  "occupied": true,
  "ldr_raw": 2700,
  "is_dark": true,
  "temperature_c": null,
  "humidity_percent": null,
  "dht_valid": false,
  "light_on": true,
  "fan_on": false,
  "ac_on": false,
  "control_mode": "automatic"
}
```

---

### 2. Inbound Command Payload (`.../command`)

```json
{
  "schema_version": 1,
  "command_id": "cmd-101",
  "device_id": "room-1",
  "target": "light",
  "action": "off",
  "mode": "manual",
  "expires_in_seconds": 60
}
```

#### Supported Targets & Actions:
- `"target": "light"`, `"action": "on" | "off"`: Overrides Room Light LED.
- `"target": "fan"`, `"action": "on" | "off"`: Overrides Fan LED (subject to DHT failsafe).
- `"target": "ac"`, `"action": "on" | "off"`: Overrides AC LED (subject to DHT failsafe).
- `"target": "all"`, `"action": "off"`: Turns all simulated loads OFF immediately.
- `"target": "automatic"`: Immediately cancels active manual overrides and returns control to sensor logic.

#### Rejection Conditions & Stable Reason Codes:
- `wrong_schema_version`: `schema_version != 1`
- `missing_command_id`: `command_id` missing or empty string
- `wrong_device_id`: `device_id != "room-1"`
- `invalid_target`: Unrecognized appliance target
- `invalid_action`: Unrecognized action (not `on` or `off`)
- `invalid_action_for_all`: Attempting `action: on` with `target: all`
- `message_too_large`: Payload exceeds 512 bytes
- `invalid_json`: Unparseable or malformed JSON
- `invalid_mode`: A non-automatic target did not use `mode: manual`
- `sensor_data_unavailable`: A climate ON command arrived before the first validated sensor sample
- `dht_invalid`: A climate ON command was blocked because DHT22 was invalid

---

### 3. Command Result Acknowledgement (`.../state`)
Published immediately after GPIO outputs are set.

#### Accepted Execution:
```json
{
  "schema_version": 1,
  "message_type": "command_result",
  "device_id": "room-1",
  "firmware_version": "2.1.0",
  "command_id": "cmd-101",
  "accepted": true,
  "reason": "command_applied",
  "control_mode": "manual_override",
  "light_on": false,
  "fan_on": true,
  "ac_on": false,
  "uptime_ms": 86520
}
```

#### Rejected Execution:
```json
{
  "schema_version": 1,
  "message_type": "command_result",
  "device_id": "room-1",
  "firmware_version": "2.1.0",
  "command_id": "cmd-102",
  "accepted": false,
  "reason": "invalid_target",
  "control_mode": "automatic",
  "uptime_ms": 87100
}
```

---

### 4. Device Status & Last Will and Testament (`.../status`)
- **Online (Retained upon broker connect)**:
  ```json
  {"schema_version":1,"message_type":"device_status","device_id":"room-1","firmware_version":"2.1.0","status":"online","uptime_ms":1200}
  ```
- **Offline (Retained Last Will and Testament)**:
  ```json
  {"schema_version":1,"message_type":"device_status","device_id":"room-1","firmware_version":"2.1.0","status":"offline"}
  ```

---

## 🛠️ Step-by-Step Self-Verification Guide

### Step 1: Automated Unit & Logic Verification Suite
Run the offline C++ test suite containing all 12 Phase 1 rules and 26 Phase 2 command/override scenarios:
```powershell
.\verify.bat
```
**Expected Output**:
```text
[Phase 1] Compiling and running Phase 1 logic tests...
Results: 12 / 12 tests passed.

[Phase 2] Compiling and running Phase 2 command and override tests...
Results: 63 / 63 tests passed.

[ALL PASS] All Phase 1 and Phase 2 tests passed cleanly!
```

### Step 2: Build ESP32 Firmware
```powershell
.\build.bat
```
Confirms clean compilation with PlatformIO and outputs binary to `.pio\build\esp32dev\firmware.bin`.

### Step 3: Run Simulation in Wokwi
1. Open [`diagram.json`](diagram.json) in VS Code / Antigravity IDE.
2. Press `F1` and select **Wokwi: Start Simulator** (or click the green Play button).
3. Open the Serial Monitor at **115200 baud**.
4. Observe Wi-Fi connect (`[WiFi] Connected! IP Address: 10.0.0.2`) and MQTT connect (`[MQTT] Subscribed to: smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/command`).

### Step 4: Monitor Telemetry via Mosquitto CLI / MQTT Explorer

#### Using Mosquitto CLI:
```powershell
mosquitto_sub -h broker.hivemq.com -p 1883 -t "smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/#" -v
```

#### Using MQTT Explorer:
1. Connect to Host: `broker.hivemq.com`, Port: `1883`.
2. Add topic subscription: `smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/#`.
3. View real-time incoming JSON messages on `/telemetry`, `/state`, and `/status`.

### Step 5: Test Command Execution

The firmware features built-in payload normalization that automatically unescapes `\"`, strips outer quotes, and trims whitespace/newlines. Commands can be sent via PowerShell, CMD, Linux, or MQTT Explorer:

#### 1. Turn Room Light OFF (Manual Override for 30s):
**Windows PowerShell (recommended):**
```powershell
'{"schema_version":1,"command_id":"cmd-001","device_id":"room-1","target":"light","action":"off","mode":"manual","expires_in_seconds":30}' | mosquitto_pub -h broker.hivemq.com -p 1883 -t "smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/command" -l
```
**Linux / macOS / Git Bash:**
```bash
mosquitto_pub -h broker.hivemq.com -p 1883 -t "smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/command" -m '{"schema_version":1,"command_id":"cmd-001","device_id":"room-1","target":"light","action":"off","mode":"manual","expires_in_seconds":30}'
```
*Expected*: Room Light LED turns OFF immediately. Serial outputs `[CMD] Manual override applied: light -> off for 30 s.` Telemetry updates to `"control_mode": "manual_override"`. After 30 seconds, `[Override] Timer expired. Restoring automatic control.` is printed and light returns to sensor rule.

#### 2. Turn ALL Loads OFF:
```powershell
'{"schema_version":1,"command_id":"cmd-002","device_id":"room-1","target":"all","action":"off","mode":"manual","expires_in_seconds":60}' | mosquitto_pub -h broker.hivemq.com -p 1883 -t "smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/command" -l
```

#### 3. Return to Automatic Mode:
```powershell
'{"schema_version":1,"command_id":"cmd-003","device_id":"room-1","target":"automatic","action":"off"}' | mosquitto_pub -h broker.hivemq.com -p 1883 -t "smart-energy-demo/siddharthranka18-smart-energy-2026/room-1/command" -l
```

---

## ⚠️ Known Boundaries & Scope Clarification

1. **Demonstration Transport**: Uses unencrypted TCP MQTT port 1883 on a public test broker (`broker.hivemq.com`). No production security or TLS is claimed.
2. **Phase 2 Scope Restriction**: This phase strictly covers embedded Wi-Fi, MQTT telemetry, command handling, and local override control. **No FastAPI, PostgreSQL, React, web dashboard, REST APIs, or real electrical power measurement** have been introduced.

