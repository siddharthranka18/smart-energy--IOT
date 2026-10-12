# IoT-Based Intelligent Energy Management System

An embedded IoT energy management and climate automation prototype designed for academic engineering demonstration. The system dynamically controls simulated lighting and multi-stage cooling appliances based on physical room occupancy, ambient lux/illumination levels, and temperature thresholds to minimize idle power waste.

---

## 📌 Phase 1 Scope & Architecture

Phase 1 focuses on embedded hardware simulation, sensor acquisition, deterministic control rules, failsafe behavior, and structured serial telemetry on the **Espressif ESP32 Dev Module**.

> [!NOTE]
> Physical electrical energy metering (voltage/current sensors) and remote telemetry (MQTT, FastAPI, PostgreSQL, React) are scheduled for later phases. Phase 1 models room appliances via simulated LED indicators.

### Subsystem Overview
- **Microcontroller**: ESP32-WROOM-32 (ESP32 DevKit-C v4)
- **Occupancy Subsystem**: Digital PIR Motion Sensor (`wokwi-pir-motion-sensor`)
- **Lighting Subsystem**: Analog LDR Photoresistor Module (`wokwi-photoresistor-sensor`) & Room Light Indicator LED
- **Climate Subsystem**: DHT22 Digital Temperature & Humidity Sensor (`wokwi-dht22`), Fan LED (Ventilation Stage), and AC LED (Active Cooling Stage)
- **Telemetry**: Non-blocking 115200 baud UART Serial Monitor (2-second cycle)

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

## ⚙️ Control Rules & Logic Matrix

The firmware operates on a priority decision matrix defined in [`src/main.cpp`](src/main.cpp):

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
```

1. **Rule 1 (Occupancy Override)**: If `occupied == false`, all simulated loads (Light, Fan, AC) are immediately turned **OFF** to eliminate phantom power consumption.
2. **Rule 2 (Smart Lighting)**: If occupied and ambient light is below threshold (`rawLdr >= LDR_DARK_THRESHOLD`, 2000 ADC), Room Light LED turns **ON**; otherwise **OFF**.
3. **Rule 3 (Stage 1 Cooling / Fan)**: If occupied and temperature $\ge 28.0^\circ\text{C}$, Fan LED turns **ON**; otherwise **OFF**.
4. **Rule 4 (Stage 2 Cooling / AC)**: If occupied and temperature $\ge 32.0^\circ\text{C}$, AC LED turns **ON**; otherwise **OFF**.
5. **Failsafe**: If DHT22 reads `NaN`, Fan and AC default safely to **OFF** while logging a diagnostic warning.

---

## 🚀 Quick Start Guide

### 1. Build the Firmware
Using the PlatformIO CLI:
```powershell
pio run
```
Or with custom environment path:
```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run
```

### 2. Launch Simulation in VS Code
1. Open [`diagram.json`](diagram.json).
2. Press `F1` and select **Wokwi: Start Simulator** (or click the green Play button on the editor).
3. Connect the Serial Monitor at **115200 baud**.

### 3. Detailed Self-Verification
Refer to [`PHASE_1_VERIFICATION.md`](PHASE_1_VERIFICATION.md) for full step-by-step interactive testing procedures, serial log samples, boundary condition testing, and automated test suite execution.
