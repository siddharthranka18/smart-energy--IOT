/**
 * ============================================================================
 * Project      : IoT-Based Intelligent Energy Management System
 * Phase        : 2 — Wi-Fi Connectivity & MQTT Telemetry / Commands
 * Platform     : ESP32 Dev Module (Wokwi Simulation & Hardware)
 * Description  : Phase 1: Sensor acquisition, deterministic energy control,
 *                fail-safe actuator output, structured serial telemetry.
 *                Phase 2: Wi-Fi connectivity, MQTT telemetry publishing,
 *                MQTT command reception, manual override with expiry, LWT,
 *                command acknowledgements, automatic reconnection.
 * ============================================================================
 * SCOPE NOTE: No FastAPI, PostgreSQL, React, dashboard, analytics, power
 *             metering, or multi-room simulation is implemented in this phase.
 *             Public MQTT on port 1883 is unencrypted — for demonstration only.
 * ============================================================================
 */

#include <Arduino.h>
#include <Adafruit_Sensor.h>
#include <DHT.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ============================================================================
// PHASE 1 — Hardware Pin Map (unchanged)
// ============================================================================
constexpr uint8_t PIN_LIGHT_LED = 2;   // Simulated Room Light LED
constexpr uint8_t PIN_FAN_LED   = 4;   // Simulated Fan LED
constexpr uint8_t PIN_AC_LED    = 5;   // Simulated AC LED
constexpr uint8_t PIN_PIR       = 14;  // PIR Motion Sensor OUT
constexpr uint8_t PIN_DHT       = 15;  // DHT22 Data Bus (single-wire)
constexpr uint8_t PIN_LDR       = 34;  // LDR Module Analog Output (ADC1_CH6)

// ============================================================================
// PHASE 1 — Control Thresholds & Calibration Constants (unchanged)
// ============================================================================
constexpr int           LDR_DARK_THRESHOLD      = 2000;    // ADC counts (Darkness threshold)
constexpr float         TEMP_FAN_THRESHOLD      = 28.0f;   // Deg C: Ventilation fan trigger
constexpr float         TEMP_AC_THRESHOLD       = 32.0f;   // Deg C: Secondary cooling / AC stage
constexpr unsigned long TELEMETRY_INTERVAL_MS   = 2000UL;  // Control & telemetry cycle period

// ============================================================================
// PHASE 2 — Wi-Fi Configuration
// ============================================================================
static const char*      WIFI_SSID               = "Wokwi-GUEST";  // Wokwi virtual network
static const char*      WIFI_PASSWORD           = "";              // No password
constexpr uint8_t       WIFI_CHANNEL            = 6;               // Wokwi Wi-Fi channel
constexpr unsigned long WIFI_RETRY_INTERVAL_MS  = 10000UL;         // Retry period when disconnected

// ============================================================================
// PHASE 2 — MQTT Configuration
// ============================================================================
static const char*      MQTT_BROKER             = "broker.hivemq.com"; // Public non-TLS demo broker
constexpr uint16_t      MQTT_PORT               = 1883;
static const char*      DEVICE_ID               = "room-1";
static const char*      TOPIC_PREFIX            = "smart-energy-demo/iot-energy-mgmt"; // Project prefix

constexpr unsigned long MQTT_RECONNECT_INTERVAL_MS = 5000UL;       // Reconnect retry interval
constexpr uint32_t      DEFAULT_OVERRIDE_SECONDS   = 60;           // Default manual override duration
constexpr int           MQTT_SCHEMA_VERSION        = 1;            // Message schema version
constexpr int           MQTT_MAX_PAYLOAD_BYTES     = 512;          // Reject oversized payloads

// Dynamically generated topic strings
static char TOPIC_TELEMETRY[128];
static char TOPIC_STATE    [128];
static char TOPIC_COMMAND  [128];
static char TOPIC_STATUS   [128];
static char MQTT_CLIENT_ID [ 64];

// ============================================================================
// Peripheral & Network Drivers
// ============================================================================
DHT dht(PIN_DHT, DHT22);
WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);

// ============================================================================
// PHASE 1 — Data Models (unchanged)
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
// PHASE 2 — Control Mode & Manual Override State
// ============================================================================
enum class ControlMode {
    AUTOMATIC,
    MANUAL_OVERRIDE
};

struct ManualOverride {
    ControlMode   mode        = ControlMode::AUTOMATIC;
    unsigned long startMs     = 0;
    unsigned long durationMs  = 0;
    bool          lightActive = false;
    bool          lightValue  = false;
    bool          fanActive   = false;
    bool          fanValue    = false;
    bool          acActive    = false;
    bool          acValue     = false;
};

// Global Runtime State
static ManualOverride g_override;
static unsigned long  g_sequenceNumber      = 0;
static unsigned long  g_lastWifiAttemptMs   = 0;
static unsigned long  g_lastMqttReconnectMs = 0;

// ============================================================================
// Forward Function Declarations
// ============================================================================
void readSensors(SensorReadings &sensors);
void computeControlLogic(const SensorReadings &sensors, ActuatorState &actuators);
void applyActuators(const ActuatorState &actuators);
void printStatus(const SensorReadings &sensors, const ActuatorState &actuators);

void buildTopicNames();
void maintainWiFiConnection();
void maintainMqttConnection();
void onMqttMessage(char* topic, byte* payload, unsigned int length);
void publishTelemetry(const SensorReadings &sensors, const ActuatorState &actuators);
void publishDeviceStatus(bool online);
void publishCommandResult(const char* commandId, bool accepted, const char* reason, const ActuatorState* actuators = nullptr);
void parseAndApplyCommand(const byte* payload, unsigned int length, ActuatorState &currentActuators);
void updateManualOverride(ActuatorState &actuators, const SensorReadings &sensors);
const char* controlModeString();

// ============================================================================
// Setup
// ============================================================================
void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 1000) {
        // Allow USB CDC / serial link to stabilize
    }

    // Configure GPIO modes (Phase 1)
    pinMode(PIN_LIGHT_LED, OUTPUT);
    pinMode(PIN_FAN_LED,   OUTPUT);
    pinMode(PIN_AC_LED,    OUTPUT);

    pinMode(PIN_PIR, INPUT);
    pinMode(PIN_LDR, INPUT);

    // Safe initial output state: all loads OFF
    digitalWrite(PIN_LIGHT_LED, LOW);
    digitalWrite(PIN_FAN_LED,   LOW);
    digitalWrite(PIN_AC_LED,    LOW);

    // Initialize DHT22
    dht.begin();

    Serial.println();
    Serial.println("==================================================");
    Serial.println("  IoT Intelligent Energy Management System (Phase 2)");
    Serial.println("  ESP32 Firmware Initialized with Wi-Fi & MQTT");
    Serial.println("==================================================");
    Serial.println();

    // Construct topic names & client ID
    buildTopicNames();

    Serial.print("[WiFi] Target SSID : "); Serial.println(WIFI_SSID);
    Serial.print("[MQTT] Broker      : "); Serial.print(MQTT_BROKER); Serial.print(":"); Serial.println(MQTT_PORT);
    Serial.print("[MQTT] Device ID   : "); Serial.println(DEVICE_ID);
    Serial.print("[MQTT] Client ID   : "); Serial.println(MQTT_CLIENT_ID);
    Serial.print("[MQTT] Telemetry   : "); Serial.println(TOPIC_TELEMETRY);
    Serial.print("[MQTT] Command     : "); Serial.println(TOPIC_COMMAND);
    Serial.println();

    // Start Wi-Fi asynchronously
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD, WIFI_CHANNEL);
    g_lastWifiAttemptMs = millis();

    // Configure MQTT client
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(onMqttMessage);
    mqttClient.setBufferSize(512);
    mqttClient.setKeepAlive(60);
}

// ============================================================================
// Main Loop (Non-blocking timing)
// ============================================================================
void loop() {
    static unsigned long lastUpdateMs = 0;
    const unsigned long currentMs = millis();

    // Maintain network connections non-blockingly
    maintainWiFiConnection();
    maintainMqttConnection();
    if (mqttClient.connected()) {
        mqttClient.loop();
    }

    // Execute state cycle every TELEMETRY_INTERVAL_MS without blocking
    if (currentMs - lastUpdateMs >= TELEMETRY_INTERVAL_MS || lastUpdateMs == 0) {
        lastUpdateMs = currentMs;

        SensorReadings sensors;
        ActuatorState actuators;

        // 1. Read and validate all sensor inputs (Phase 1)
        readSensors(sensors);

        // 2. Evaluate energy management control rules (Phase 1)
        computeControlLogic(sensors, actuators);

        // 3. Layer Phase 2 manual override state if active
        updateManualOverride(actuators, sensors);

        // 4. Drive physical/simulated actuators
        applyActuators(actuators);

        // 5. Output structured serial diagnostics
        printStatus(sensors, actuators);

        // 6. Publish MQTT telemetry if connected
        if (mqttClient.connected()) {
            publishTelemetry(sensors, actuators);
        }
    }
}

// ============================================================================
// PHASE 2 — Networking & MQTT Implementation
// ============================================================================

void buildTopicNames() {
    uint32_t chipId = static_cast<uint32_t>(ESP.getEfuseMac() >> 24);
    snprintf(MQTT_CLIENT_ID, sizeof(MQTT_CLIENT_ID), "iot-energy-%s-%06lX", DEVICE_ID, (unsigned long)chipId);

    snprintf(TOPIC_TELEMETRY, sizeof(TOPIC_TELEMETRY), "%s/%s/telemetry", TOPIC_PREFIX, DEVICE_ID);
    snprintf(TOPIC_STATE,     sizeof(TOPIC_STATE),     "%s/%s/state",     TOPIC_PREFIX, DEVICE_ID);
    snprintf(TOPIC_COMMAND,   sizeof(TOPIC_COMMAND),   "%s/%s/command",   TOPIC_PREFIX, DEVICE_ID);
    snprintf(TOPIC_STATUS,    sizeof(TOPIC_STATUS),    "%s/%s/status",    TOPIC_PREFIX, DEVICE_ID);
}

void maintainWiFiConnection() {
    static bool wasConnected = false;

    if (WiFi.status() == WL_CONNECTED) {
        if (!wasConnected) {
            wasConnected = true;
            Serial.print("[WiFi] Connected! IP Address: ");
            Serial.println(WiFi.localIP());
        }
        return;
    }

    if (wasConnected) {
        wasConnected = false;
        Serial.println("[WiFi] Connection dropped.");
    }

    const unsigned long now = millis();
    if (now - g_lastWifiAttemptMs >= WIFI_RETRY_INTERVAL_MS) {
        g_lastWifiAttemptMs = now;
        Serial.println("[WiFi] Re-attempting connection to AP...");
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD, WIFI_CHANNEL);
    }
}

void maintainMqttConnection() {
    if (mqttClient.connected()) return;
    if (WiFi.status() != WL_CONNECTED) return; // Wait until Wi-Fi is up

    const unsigned long now = millis();
    if (now - g_lastMqttReconnectMs < MQTT_RECONNECT_INTERVAL_MS) return;
    g_lastMqttReconnectMs = now;

    // Retained LWT payload for unexpected disconnection
    char lwtPayload[80];
    snprintf(lwtPayload, sizeof(lwtPayload), "{\"device_id\":\"%s\",\"status\":\"offline\"}", DEVICE_ID);

    Serial.print("[MQTT] Connecting to broker as ");
    Serial.print(MQTT_CLIENT_ID);
    Serial.print(" ...");

    bool ok = mqttClient.connect(
        MQTT_CLIENT_ID,
        nullptr, nullptr,      // Unauthenticated public demo
        TOPIC_STATUS,          // LWT topic
        0,                     // LWT QoS
        true,                  // Retain LWT
        lwtPayload             // LWT message
    );

    if (ok) {
        Serial.println(" CONNECTED!");
        // Subscribe to command topic
        if (mqttClient.subscribe(TOPIC_COMMAND, 1)) {
            Serial.print("[MQTT] Subscribed to: ");
            Serial.println(TOPIC_COMMAND);
        } else {
            Serial.println("[MQTT] ERROR: Failed to subscribe to command topic.");
        }
        // Announce online status
        publishDeviceStatus(true);
    } else {
        Serial.print(" FAILED (rc=");
        Serial.print(mqttClient.state());
        Serial.println("). Retrying shortly.");
    }
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
    Serial.print("[MQTT] Received message on topic: ");
    Serial.println(topic);

    if (strcmp(topic, TOPIC_COMMAND) != 0) {
        return; // Ignore other topics
    }

    // Capture current actuator outputs
    ActuatorState current;
    current.lightOn = (digitalRead(PIN_LIGHT_LED) == HIGH);
    current.fanOn   = (digitalRead(PIN_FAN_LED)   == HIGH);
    current.acOn    = (digitalRead(PIN_AC_LED)    == HIGH);

    parseAndApplyCommand(payload, length, current);
}

void publishTelemetry(const SensorReadings &sensors, const ActuatorState &actuators) {
    g_sequenceNumber++;

    StaticJsonDocument<384> doc;
    doc["schema_version"]   = MQTT_SCHEMA_VERSION;
    doc["message_type"]     = "telemetry";
    doc["device_id"]        = DEVICE_ID;
    doc["sequence"]         = g_sequenceNumber;
    doc["uptime_ms"]        = millis();
    doc["occupied"]         = sensors.occupied;
    doc["ldr_raw"]          = sensors.rawLdr;
    doc["is_dark"]          = sensors.isDark;

    if (sensors.dhtValid) {
        doc["temperature_c"]    = sensors.temperature;
        doc["humidity_percent"] = sensors.humidity;
    } else {
        doc["temperature_c"]    = serialized("null");
        doc["humidity_percent"] = serialized("null");
    }

    doc["dht_valid"]    = sensors.dhtValid;
    doc["light_on"]     = actuators.lightOn;
    doc["fan_on"]       = actuators.fanOn;
    doc["ac_on"]        = actuators.acOn;
    doc["control_mode"] = controlModeString();

    char buffer[384];
    serializeJson(doc, buffer, sizeof(buffer));

    bool ok = mqttClient.publish(TOPIC_TELEMETRY, buffer, false);
    Serial.print("[MQTT] Telemetry #");
    Serial.print(g_sequenceNumber);
    Serial.print(" publish ");
    Serial.println(ok ? "SUCCESS" : "FAILED");
    Serial.print("[MQTT] Payload: ");
    Serial.println(buffer);
}

void publishDeviceStatus(bool online) {
    StaticJsonDocument<128> doc;
    doc["device_id"] = DEVICE_ID;
    doc["status"]    = online ? "online" : "offline";
    doc["uptime_ms"] = millis();

    char buffer[128];
    serializeJson(doc, buffer, sizeof(buffer));

    bool ok = mqttClient.publish(TOPIC_STATUS, buffer, true); // Retained
    Serial.print("[MQTT] Device status (");
    Serial.print(online ? "online" : "offline");
    Serial.print(") publish ");
    Serial.println(ok ? "SUCCESS" : "FAILED");
}

void publishCommandResult(const char* commandId, bool accepted, const char* reason, const ActuatorState* actuators) {
    StaticJsonDocument<256> doc;
    doc["schema_version"] = MQTT_SCHEMA_VERSION;
    doc["message_type"]   = "command_result";
    doc["device_id"]      = DEVICE_ID;
    doc["command_id"]     = commandId ? commandId : "";
    doc["accepted"]       = accepted;
    doc["reason"]         = reason;
    doc["control_mode"]   = controlModeString();

    if (actuators != nullptr) {
        doc["light_on"]   = actuators->lightOn;
        doc["fan_on"]     = actuators->fanOn;
        doc["ac_on"]      = actuators->acOn;
    }
    doc["uptime_ms"]      = millis();

    char buffer[256];
    serializeJson(doc, buffer, sizeof(buffer));

    bool ok = mqttClient.publish(TOPIC_STATE, buffer, false);
    Serial.print("[MQTT] Command result publish ");
    Serial.println(ok ? "SUCCESS" : "FAILED");
    Serial.print("[MQTT] Payload: ");
    Serial.println(buffer);
}

void parseAndApplyCommand(const byte* payload, unsigned int length, ActuatorState &currentActuators) {
    if (length == 0 || length > static_cast<unsigned int>(MQTT_MAX_PAYLOAD_BYTES)) {
        Serial.println("[CMD] Rejected: payload length invalid or oversized.");
        publishCommandResult("", false, "message_too_large");
        return;
    }

    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) {
        Serial.print("[CMD] Rejected: malformed JSON: ");
        Serial.println(err.c_str());
        publishCommandResult("", false, "invalid_json");
        return;
    }

    const char* commandId = doc["command_id"] | "";
    const char* deviceId  = doc["device_id"]  | "";
    const char* target    = doc["target"]     | "";
    const char* action    = doc["action"]     | "";
    int schemaVersion     = doc["schema_version"] | 0;
    uint32_t expirySec    = doc["expires_in_seconds"] | DEFAULT_OVERRIDE_SECONDS;

    // 1. Schema check
    if (schemaVersion != MQTT_SCHEMA_VERSION) {
        Serial.println("[CMD] Rejected: unsupported schema_version.");
        publishCommandResult(commandId, false, "wrong_schema_version");
        return;
    }

    // 2. Command ID check
    if (strlen(commandId) == 0) {
        Serial.println("[CMD] Rejected: missing or empty command_id.");
        publishCommandResult(commandId, false, "missing_command_id");
        return;
    }

    // 3. Device ID check
    if (strcmp(deviceId, DEVICE_ID) != 0) {
        Serial.println("[CMD] Rejected: device_id mismatch.");
        publishCommandResult(commandId, false, "wrong_device_id");
        return;
    }

    // 4. Target validation
    const bool targetLight = (strcmp(target, "light") == 0);
    const bool targetFan   = (strcmp(target, "fan")   == 0);
    const bool targetAc    = (strcmp(target, "ac")    == 0);
    const bool targetAll   = (strcmp(target, "all")   == 0);
    const bool targetAuto  = (strcmp(target, "automatic") == 0);

    if (!targetLight && !targetFan && !targetAc && !targetAll && !targetAuto) {
        Serial.println("[CMD] Rejected: unknown target.");
        publishCommandResult(commandId, false, "invalid_target");
        return;
    }

    // Return to automatic mode immediately
    if (targetAuto) {
        g_override = ManualOverride(); // Reset
        Serial.println("[CMD] Reset to automatic control mode.");
        publishCommandResult(commandId, true, "returned_to_automatic", &currentActuators);
        return;
    }

    // Action validation
    const bool actionOn  = (strcmp(action, "on")  == 0);
    const bool actionOff = (strcmp(action, "off") == 0);

    if (!actionOn && !actionOff) {
        Serial.println("[CMD] Rejected: unknown action.");
        publishCommandResult(commandId, false, "invalid_action");
        return;
    }

    if (expirySec == 0) expirySec = DEFAULT_OVERRIDE_SECONDS;
    const unsigned long now = millis();

    // Target ALL
    if (targetAll) {
        if (!actionOff) {
            Serial.println("[CMD] Rejected: target 'all' only supports action 'off'.");
            publishCommandResult(commandId, false, "invalid_action_for_all");
            return;
        }

        g_override.mode        = ControlMode::MANUAL_OVERRIDE;
        g_override.startMs     = now;
        g_override.durationMs  = static_cast<unsigned long>(expirySec) * 1000UL;
        g_override.lightActive = true; g_override.lightValue = false;
        g_override.fanActive   = true; g_override.fanValue   = false;
        g_override.acActive    = true; g_override.acValue    = false;

        currentActuators.lightOn = false;
        currentActuators.fanOn   = false;
        currentActuators.acOn    = false;

        applyActuators(currentActuators);
        Serial.printf("[CMD] ALL loads turned OFF via manual override (%lu s).\n", (unsigned long)expirySec);
        publishCommandResult(commandId, true, "command_applied", &currentActuators);
        return;
    }

    // Single target override
    const bool desiredState = actionOn;
    g_override.mode       = ControlMode::MANUAL_OVERRIDE;
    g_override.startMs    = now;
    g_override.durationMs = static_cast<unsigned long>(expirySec) * 1000UL;

    if (targetLight) {
        g_override.lightActive = true;
        g_override.lightValue  = desiredState;
        currentActuators.lightOn = desiredState;
    } else if (targetFan) {
        g_override.fanActive = true;
        g_override.fanValue  = desiredState;
        currentActuators.fanOn = desiredState;
    } else if (targetAc) {
        g_override.acActive = true;
        g_override.acValue  = desiredState;
        currentActuators.acOn = desiredState;
    }

    applyActuators(currentActuators);
    Serial.printf("[CMD] Manual override applied: %s -> %s for %lu s.\n", target, action, (unsigned long)expirySec);
    publishCommandResult(commandId, true, "command_applied", &currentActuators);
}

void updateManualOverride(ActuatorState &actuators, const SensorReadings &sensors) {
    if (g_override.mode != ControlMode::MANUAL_OVERRIDE) return;

    // Check expiration using safe unsigned difference
    if (millis() - g_override.startMs >= g_override.durationMs) {
        g_override = ManualOverride(); // Reset to AUTOMATIC
        Serial.println("[Override] Timer expired. Restoring automatic control.");
        return;
    }

    // Apply specific overrides on top of automatic computations
    if (g_override.lightActive) {
        actuators.lightOn = g_override.lightValue;
    }
    if (g_override.fanActive) {
        // DHT failsafe protection: invalid DHT forces climate loads safely OFF
        actuators.fanOn = (g_override.fanValue && sensors.dhtValid);
    }
    if (g_override.acActive) {
        // DHT failsafe protection: invalid DHT forces climate loads safely OFF
        actuators.acOn = (g_override.acValue && sensors.dhtValid);
    }
}

const char* controlModeString() {
    return (g_override.mode == ControlMode::MANUAL_OVERRIDE) ? "manual_override" : "automatic";
}

// ============================================================================
// PHASE 1 — Modular Implementation Functions (unchanged logic)
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
    Serial.print("s | Mode: ");
    Serial.println(controlModeString());
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
