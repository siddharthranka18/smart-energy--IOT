# Phase 1 Implementation & Self-Verification Guide

This document explains **what was implemented in Phase 1** and provides a **step-by-step procedure to verify the entire system yourself**.

---

## Part 1: What Was Done in Phase 1

### 1. Hardware Simulation Architecture (`diagram.json`)
The Wokwi simulation was upgraded from a single-LED circuit to a multi-sensor, multi-actuator smart room environment:
- **ESP32 Dev Module**: `board-esp32-devkit-c-v4` microcontroller core.
- **PIR Sensor (`pir1`)**: `wokwi-pir-motion-sensor` on GPIO 14 (Occupancy detection).
- **LDR Module (`ldr1`)**: `wokwi-photoresistor-sensor` on GPIO 34 (Analog ambient light).
- **DHT22 Sensor (`dht1`)**: `wokwi-dht22` on GPIO 15 (Single-wire temperature & humidity bus).
- **3 Simulated Loads & Resistors**:
  - Room Light LED (`yellow`) on GPIO 2 with 220Ω resistor.
  - Fan LED (`blue`) on GPIO 4 with 220Ω resistor.
  - AC LED (`orange`) on GPIO 5 with 220Ω resistor.

### 2. PlatformIO Configuration (`platformio.ini`)
- Set UART baud rate: `monitor_speed = 115200`.
- Integrated required libraries:
  - `adafruit/DHT sensor library @ ^1.4.6`
  - `adafruit/Adafruit Unified Sensor @ ^1.1.14`

### 3. Modular Firmware (`src/main.cpp`)
- **Non-blocking timing**: Replaced blocking `delay()` with `millis()` cycle scheduling (`TELEMETRY_INTERVAL_MS = 2000UL`).
- **Separation of concerns**:
  - `readSensors()`: Hardware sampling and validity check.
  - `computeControlLogic()`: Deterministic priority decision matrix.
  - `applyActuators()`: GPIO driver.
  - `printStatus()`: Structured serial diagnostics.
- **Deterministic control rules**:
  - **Rule 1 (Unoccupied Room)**: Turn all 3 loads OFF.
  - **Rule 2 (Lighting)**: Occupied + Dark ambient light (`rawLdr >= 2000`) -> Light ON, else OFF.
  - **Rule 3 (Ventilation)**: Occupied + Temperature $\ge 28.0^\circ\text{C}$ -> Fan ON, else OFF.
  - **Rule 4 (Active Cooling)**: Occupied + Temperature $\ge 32.0^\circ\text{C}$ -> AC ON, else OFF.
  - **Failsafe**: If DHT22 reads `NaN`, climate loads (Fan and AC) safely default to OFF while Room Light continues to respond to PIR and LDR.

### 4. Automated Verification Test Suite (`test/verify_logic.cpp`)
- A standalone C++ test harness that verifies all 12 operational and boundary cases in automated fashion with zero hardware required.

---

## Part 2: Step-by-Step Self-Verification Guide

Follow these steps to verify Phase 1 on your own machine.

### Verification Step 1: Re-compile Firmware via PlatformIO
Confirm that the code compiles without any errors or missing dependencies:

Open PowerShell in the project directory and run:
```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run
```
*(If `pio` is in your system PATH, you can simply type `pio run`)*.

**Expected Result:**
```text
========================= [SUCCESS] Took ~1.5 seconds =========================
```
Ensure that `.pio/build/esp32dev/firmware.bin` and `.pio/build/esp32dev/firmware.elf` are generated.

---

### Verification Step 2: Run the Automated C++ Test Suite
To verify all decision rules and edge cases immediately:

```powershell
C:\MinGW\bin\g++.exe -std=c++11 test/verify_logic.cpp -o test/verify_logic.exe
.\test\verify_logic.exe
```

**Expected Result:**
```text
============================================================
  RUNNING PHASE 1 AUTOMATED LOGIC VERIFICATION SUITE
============================================================
[PASS] 1. Empty Room (Unoccupied, Dark, Cold)
[PASS] 2. Empty Room (Unoccupied, Hot 35C, Dark)
[PASS] 3. Occupied & Bright Room (Comfort 25C)
[PASS] 4. Occupied & Dark Room (Comfort 25C)
[PASS] 5. Occupied Room at 27.9C (Boundary: Temp < 28C)
[PASS] 6. Occupied Room at 28.0C (Boundary: Fan Trigger)
[PASS] 7. Occupied Room at 30.0C (Fan ON, AC OFF)
[PASS] 8. Occupied Room at 31.9C (Boundary: AC still OFF)
[PASS] 9. Occupied Room at 32.0C (Boundary: AC Trigger)
[PASS] 10. Occupied Room at 35.0C & Dark (Light ON, Fan ON, AC ON)
[PASS] 11. Failsafe: DHT22 NaN / Invalid Read (Occupied & Dark)
[PASS] 12. Failsafe: DHT22 NaN / Invalid Read (Occupied & Bright)
------------------------------------------------------------
Results: 12 / 12 tests passed.
============================================================
```

---

### Verification Step 3: Launch Wokwi Simulation in VS Code
1. Open the project in VS Code.
2. Ensure the **Wokwi Simulator** extension (`wokwi.wokwi-vscode`) is installed and activated.
3. Open [`diagram.json`](diagram.json).
4. Press `F1` (or `Ctrl + Shift + P`) to open the Command Palette.
5. Type and select: **`Wokwi: Start Simulator`** (or click the green **Play** button inside the editor tab).
6. The simulator will boot the ESP32 using the `.pio/build/esp32dev/firmware.bin` binary.

---

### Verification Step 4: Interact with Virtual Sensors
Once the simulation is running:

#### 1. Test Occupancy (PIR Sensor)
- **Action**: Click on the PIR sensor (`pir1`, blue round sensor on the upper left).
- A pop-up bubble appears with a button labeled **"Simulate Motion"**.
- Click **"Simulate Motion"**.
- **Observation**: The sensor triggers HIGH for 5 seconds. When motion stops, it drops to LOW (Empty).

#### 2. Test Ambient Light (Photoresistor / LDR)
- **Action**: Click on the LDR sensor module (`ldr1`, green board on the mid-left).
- A slider bar appears showing current illumination (lux).
- **Simulate Daylight / Bright**: Drag slider to the right (e.g. > 500 lux).
  - Raw ADC reading drops below 2000. Classified as `BRIGHT`.
- **Simulate Night / Dark**: Drag slider to the left (e.g. < 50 lux).
  - Raw ADC reading rises above 2000. Classified as `DARK`.

#### 3. Test Room Temperature (DHT22 Sensor)
- **Action**: Click on the DHT22 sensor (`dht1`, white sensor on the bottom-left).
- Two sliders appear: **Temperature (°C)** and **Humidity (%)**.
- **Cold / Comfort (< 28°C)**: Slide to 24°C.
- **Mild Heat (28°C to 31.9°C)**: Slide to 30°C.
- **High Heat ($\ge$ 32°C)**: Slide to 34°C.

---

### Verification Step 5: Expected Behavior Verification Matrix

Execute each of these scenarios in the simulation and verify LED states and Serial Monitor output:

| Scenario | PIR Input | LDR Slider | DHT22 Temp | Room Light LED (GPIO 2) | Fan LED (GPIO 4) | AC LED (GPIO 5) | What it proves |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A. Empty Room** | Do not click motion (Idle) | Slide to Dark (< 50 lux) | 35.0°C | **OFF** | **OFF** | **OFF** | Energy saving: unoccupied room shuts down all loads regardless of temperature or darkness. |
| **B. Occupied & Bright** | Click "Simulate Motion" | Slide to Bright (> 500 lux) | 24.0°C | **OFF** | **OFF** | **OFF** | Sufficient daylight; no lighting required. Comfortable temperature. |
| **C. Occupied & Dark** | Click "Simulate Motion" | Slide to Dark (< 50 lux) | 24.0°C | **ON** 💡 | **OFF** | **OFF** | Low light triggers lighting load only. |
| **D. Occupied @ 27°C** | Click "Simulate Motion" | Slide to Bright | 27.0°C | **OFF** | **OFF** | **OFF** | Below fan threshold (28°C); fan remains idle. |
| **E. Occupied @ 30°C** | Click "Simulate Motion" | Slide to Bright | 30.0°C | **OFF** | **ON** 🌀 | **OFF** | Stage 1 cooling active (Fan ON); AC remains OFF to save energy. |
| **F. Occupied @ 33°C** | Click "Simulate Motion" | Slide to Bright | 33.0°C | **OFF** | **ON** 🌀 | **ON** ❄️ | Stage 2 cooling active (Fan ON and AC ON) due to extreme heat. |
| **G. DHT22 Disconnect/Fault** | Click "Simulate Motion" | Slide to Dark | `NaN` / fault | **ON** 💡 | **OFF** | **OFF** | Failsafe: climate loads safely shut down; lighting remains operational. |

---

### Verification Step 6: Verify Serial Monitor Output Format

In the VS Code Terminal or Wokwi Serial Monitor tab (115200 baud), check that the output matches this structure every 2 seconds:

```text
==================================================
[STATUS] Cycle: 6 | Uptime: 12s
--------------------------------------------------
Occupancy         : OCCUPIED (Motion Detected)
Ambient Light     : Raw ADC = 2840 | DARK (Dark Threshold >= 2000)
Temperature       : 30.5 deg C
Humidity          : 55.0 %
Simulated Loads   :
  - Room Light    : ON
  - Fan (Vent)    : ON (Triggered - Temp >= 28.0 C)
  - AC (Cooling)  : OFF (Idle - Temp < 32.0 C)
Sensor Diagnostics: HEALTHY (All sensors operational)
==================================================
```

---

## Part 3: Threshold Tuning & Configuration

To adapt thresholds for custom laboratory conditions, edit the named constants at the top of [`src/main.cpp`](src/main.cpp#L26-L32):

```cpp
// Darkness threshold: higher ADC count indicates lower lux in Wokwi
constexpr int   LDR_DARK_THRESHOLD   = 2000;   // 0 to 4095

// Stage 1 ventilation fan setpoint
constexpr float TEMP_FAN_THRESHOLD   = 28.0f;  // Deg C

// Stage 2 active refrigeration AC setpoint
constexpr float TEMP_AC_THRESHOLD    = 32.0f;  // Deg C

// Status reporting cycle time
constexpr unsigned long TELEMETRY_INTERVAL_MS = 2000UL;
```

After modifying constants, re-run `pio run` to rebuild the binary.

---

## Part 4: Troubleshooting Checklist

| Issue | Cause | Fix |
| :--- | :--- | :--- |
| **Serial Monitor shows gibberish characters** | Baud rate mismatch | Ensure Serial Monitor is set to **115200 baud** (matches `Serial.begin(115200)` and `monitor_speed = 115200`). |
| **Wokwi says firmware binary not found** | Firmware hasn't been built yet | Run `& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run` before starting simulation. |
| **DHT22 reads `ERROR (NaN)`** | Wiring mismatch or timing collision | Verify `diagram.json` has `dht1:SDA` connected to `esp:15`. Ensure sample interval is $\ge 2000\,\text{ms}$. |
| **All LEDs remain OFF despite motion** | Sensor sliders still at defaults | Click each sensor on the canvas to open their control widgets and adjust sliders. |
