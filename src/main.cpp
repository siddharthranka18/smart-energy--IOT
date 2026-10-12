/**
 * ============================================================================
 * Project      : IoT-Based Intelligent Energy Management System (Phase 1)
 * Platform     : ESP32 Dev Module (Wokwi Simulation & Hardware)
 * Author       : Senior Embedded Systems Engineer
 * Description  : Core sensor acquisition, deterministic energy management rules,
 *                fail-safe actuator control, and non-blocking serial telemetry.
 * ============================================================================
 */

#include <Arduino.h>
#include <Adafruit_Sensor.h>
#include <DHT.h>

// ============================================================================
// Hardware Pin Map
// ============================================================================
constexpr uint8_t PIN_LIGHT_LED = 2;   // Simulated Room Light LED
constexpr uint8_t PIN_FAN_LED   = 4;   // Simulated Fan LED
constexpr uint8_t PIN_AC_LED    = 5;   // Simulated AC LED
constexpr uint8_t PIN_PIR       = 14;  // PIR Motion Sensor OUT
constexpr uint8_t PIN_DHT       = 15;  // DHT22 Data Bus (Single-wire)
constexpr uint8_t PIN_LDR       = 34;  // LDR Module Analog Output (ADC1_CH6)

// ============================================================================
// Configurable Control Thresholds & Calibration Constants
// ============================================================================
// ESP32 ADC: 12-bit resolution (0 to 4095).
// In the Wokwi LDR sensor module, higher resistance in darkness yields a higher
// analog voltage/ADC reading. Values >= threshold indicate a DARK room.
constexpr int   LDR_DARK_THRESHOLD   = 2000;   // ADC counts (Darkness threshold)
constexpr float TEMP_FAN_THRESHOLD   = 28.0f;  // Deg C: Ventilation fan trigger
constexpr float TEMP_AC_THRESHOLD    = 32.0f;  // Deg C: Secondary cooling / AC stage

// Telemetry & Periodic Sampling Interval
constexpr unsigned long TELEMETRY_INTERVAL_MS = 2000UL;

// ============================================================================
// Peripheral Drivers
// ============================================================================
DHT dht(PIN_DHT, DHT22);

// ============================================================================
// Data Models
// ============================================================================
struct SensorReadings {
    bool  occupied;         // true = Motion detected, false = Empty room
    int   rawLdr;           // 0 - 4095 ADC counts
    bool  isDark;           // true if rawLdr >= LDR_DARK_THRESHOLD
    float temperature;      // Deg C
    float humidity;         // % RH
    bool  dhtValid;         // true if temperature & humidity are valid numbers
};

struct ActuatorState {
    bool lightOn;           // Room Light state
    bool fanOn;             // Fan state
    bool acOn;              // AC state
};

// ============================================================================
// Forward Function Declarations
// ============================================================================
void readSensors(SensorReadings &sensors);
void computeControlLogic(const SensorReadings &sensors, ActuatorState &actuators);
void applyActuators(const ActuatorState &actuators);
void printStatus(const SensorReadings &sensors, const ActuatorState &actuators);

// ============================================================================
// Setup
// ============================================================================
void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 1000) {
        // Allow USB CDC / serial link to stabilize
    }

    // Configure GPIO modes
    pinMode(PIN_LIGHT_LED, OUTPUT);
    pinMode(PIN_FAN_LED, OUTPUT);
    pinMode(PIN_AC_LED, OUTPUT);

    pinMode(PIN_PIR, INPUT);
    pinMode(PIN_LDR, INPUT); // ADC1 input

    // Safe initial output state: all simulated loads OFF
    digitalWrite(PIN_LIGHT_LED, LOW);
    digitalWrite(PIN_FAN_LED, LOW);
    digitalWrite(PIN_AC_LED, LOW);

    // Initialize sensors
    dht.begin();

    Serial.println();
    Serial.println("==================================================");
    Serial.println("  IoT Intelligent Energy Management System (Phase 1)");
    Serial.println("  ESP32 Firmware Initialized Successfully");
    Serial.println("==================================================");
    Serial.println();
}

// ============================================================================
// Main Loop (Non-blocking timing)
// ============================================================================
void loop() {
    static unsigned long lastUpdateMs = 0;
    const unsigned long currentMs = millis();

    // Execute state cycle every TELEMETRY_INTERVAL_MS without blocking
    if (currentMs - lastUpdateMs >= TELEMETRY_INTERVAL_MS || lastUpdateMs == 0) {
        lastUpdateMs = currentMs;

        SensorReadings sensors;
        ActuatorState actuators;

        // 1. Read and validate all sensor inputs
        readSensors(sensors);

        // 2. Evaluate energy management control rules
        computeControlLogic(sensors, actuators);

        // 3. Drive physical/simulated actuators
        applyActuators(actuators);

        // 4. Output structured serial diagnostics
        printStatus(sensors, actuators);
    }

    // Free cycles for future background tasks (e.g., WiFi, MQTT)
}

// ============================================================================
// Modular Implementation Functions
// ============================================================================

/**
 * Reads all hardware inputs and validates sensor integrity.
 */
void readSensors(SensorReadings &sensors) {
    // 1. Digital occupancy sensor (PIR)
    sensors.occupied = (digitalRead(PIN_PIR) == HIGH);

    // 2. Analog ambient light sensor (LDR)
    sensors.rawLdr = analogRead(PIN_LDR);
    sensors.isDark = (sensors.rawLdr >= LDR_DARK_THRESHOLD);

    // 3. Environmental sensor (DHT22)
    sensors.temperature = dht.readTemperature();
    sensors.humidity    = dht.readHumidity();

    // Check for sensor fault or invalid read
    if (isnan(sensors.temperature) || isnan(sensors.humidity)) {
        sensors.dhtValid = false;
    } else {
        sensors.dhtValid = true;
    }
}

/**
 * Deterministic energy management decision matrix:
 * 
 * Rule 1: Empty room -> All loads OFF (Light, Fan, AC).
 * Rule 2: Occupied room + Dark ambient light -> Room Light ON, else OFF.
 * Rule 3: Occupied room + Temperature >= 28.0 C -> Fan ON, else OFF.
 * Rule 4: Occupied room + Temperature >= 32.0 C -> AC ON, else OFF (Staged cooling).
 * Failsafe: If DHT reading is invalid, climate loads (Fan & AC) default safely to OFF.
 */
void computeControlLogic(const SensorReadings &sensors, ActuatorState &actuators) {
    // Rule 1: Room unoccupied -> shut down all loads immediately to eliminate phantom draw
    if (!sensors.occupied) {
        actuators.lightOn = false;
        actuators.fanOn   = false;
        actuators.acOn    = false;
        return;
    }

    // Room is occupied: evaluate individual subsystems

    // Rule 2: Lighting Control
    actuators.lightOn = sensors.isDark;

    // Failsafe check for climate subsystem
    if (!sensors.dhtValid) {
        // Safe deterministic default when temperature cannot be reliably verified
        actuators.fanOn = false;
        actuators.acOn  = false;
        return;
    }

    // Rule 3: Primary Stage Ventilation / Fan Control
    actuators.fanOn = (sensors.temperature >= TEMP_FAN_THRESHOLD);

    // Rule 4: Secondary Stage Active Refrigeration / AC Control
    actuators.acOn = (sensors.temperature >= TEMP_AC_THRESHOLD);
}

/**
 * Writes computed states to GPIO output pins.
 */
void applyActuators(const ActuatorState &actuators) {
    digitalWrite(PIN_LIGHT_LED, actuators.lightOn ? HIGH : LOW);
    digitalWrite(PIN_FAN_LED,   actuators.fanOn   ? HIGH : LOW);
    digitalWrite(PIN_AC_LED,    actuators.acOn    ? HIGH : LOW);
}

/**
 * Transmits structured status update to the Serial monitor every 2 seconds.
 */
void printStatus(const SensorReadings &sensors, const ActuatorState &actuators) {
    static unsigned long cycleCount = 0;
    cycleCount++;

    Serial.println("==================================================");
    Serial.print("[STATUS] Cycle: ");
    Serial.print(cycleCount);
    Serial.print(" | Uptime: ");
    Serial.print(millis() / 1000);
    Serial.println("s");
    Serial.println("--------------------------------------------------");

    // Occupancy
    Serial.print("Occupancy         : ");
    if (sensors.occupied) {
        Serial.println("OCCUPIED (Motion Detected)");
    } else {
        Serial.println("UNOCCUPIED (Idle)");
    }

    // Ambient Light
    Serial.print("Ambient Light     : Raw ADC = ");
    Serial.print(sensors.rawLdr);
    Serial.print(" | ");
    Serial.print(sensors.isDark ? "DARK" : "BRIGHT");
    Serial.print(" (Dark Threshold >= ");
    Serial.print(LDR_DARK_THRESHOLD);
    Serial.println(")");

    // Temperature & Humidity
    Serial.print("Temperature       : ");
    if (sensors.dhtValid) {
        Serial.print(sensors.temperature, 1);
        Serial.println(" deg C");
    } else {
        Serial.println("ERROR (NaN / Read Failure)");
    }

    Serial.print("Humidity          : ");
    if (sensors.dhtValid) {
        Serial.print(sensors.humidity, 1);
        Serial.println(" %");
    } else {
        Serial.println("ERROR (NaN / Read Failure)");
    }

    // Simulated Loads
    Serial.println("Simulated Loads   :");
    Serial.print("  - Room Light    : ");
    Serial.println(actuators.lightOn ? "ON" : "OFF");

    Serial.print("  - Fan (Vent)    : ");
    Serial.print(actuators.fanOn ? "ON" : "OFF");
    if (!sensors.occupied) {
        Serial.println(" (Disabled - Unoccupied)");
    } else if (!sensors.dhtValid) {
        Serial.println(" (Safe Default - Sensor Error)");
    } else if (sensors.temperature >= TEMP_FAN_THRESHOLD) {
        Serial.println(" (Triggered - Temp >= 28.0 C)");
    } else {
        Serial.println(" (Idle - Temp < 28.0 C)");
    }

    Serial.print("  - AC (Cooling)  : ");
    Serial.print(actuators.acOn ? "ON" : "OFF");
    if (!sensors.occupied) {
        Serial.println(" (Disabled - Unoccupied)");
    } else if (!sensors.dhtValid) {
        Serial.println(" (Safe Default - Sensor Error)");
    } else if (sensors.temperature >= TEMP_AC_THRESHOLD) {
        Serial.println(" (Triggered - Temp >= 32.0 C)");
    } else {
        Serial.println(" (Idle - Temp < 32.0 C)");
    }

    // Sensor Diagnostics
    Serial.print("Sensor Diagnostics: ");
    if (sensors.dhtValid) {
        Serial.println("HEALTHY (All sensors operational)");
    } else {
        Serial.println("WARNING (DHT22 reading invalid - safe climate defaults active)");
    }

    Serial.println("==================================================");
    Serial.println();
}
