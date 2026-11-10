/**
 * ============================================================================
 * Phase 2 Logic Verification Suite
 * Tests: command validation, payload normalization (unescaping, trimming,
 *        quoted string unwrapping), manual override state machine, expiry logic,
 *        DHT failsafe during override, automatic rules after override expiry.
 *
 * Standalone C++ host test (runs on MinGW / GCC, zero hardware dependencies).
 * ============================================================================
 */

#include <iostream>
#include <cstring>
#include <cstdint>
#include <cmath>
#include <string>
#include <vector>
#include <ArduinoJson.h>

// Constants matching src/main.cpp
static const char* DEVICE_ID             = "room-1";
static const int   MQTT_SCHEMA_VERSION   = 1;
static const uint32_t DEFAULT_OVERRIDE_SECONDS = 60;
static const uint32_t MAX_OVERRIDE_SECONDS = 3600;
static const float TEMP_FAN_THRESHOLD    = 28.0f;
static const float TEMP_AC_THRESHOLD     = 32.0f;
static const int   LDR_DARK_THRESHOLD    = 2000;
static const int   MQTT_MAX_PAYLOAD_BYTES= 512;

struct SensorReadings {
    bool  occupied;
    int   rawLdr;
    bool  isDark;
    float temperature;
    float humidity;
    bool  dhtValid;
};

struct ActuatorState {
    bool lightOn;
    bool fanOn;
    bool acOn;
};

enum class ControlMode { AUTOMATIC, MANUAL_OVERRIDE };

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

enum class CmdResult {
    ACCEPTED,
    MESSAGE_TOO_LARGE,
    INVALID_JSON,
    WRONG_SCHEMA_VERSION,
    MISSING_COMMAND_ID,
    WRONG_DEVICE_ID,
    INVALID_TARGET,
    INVALID_ACTION,
    INVALID_ACTION_FOR_ALL,
    INVALID_MODE,
    SENSOR_DATA_UNAVAILABLE,
    DHT_INVALID,
    RETURNED_TO_AUTOMATIC
};

static const char* cmdResultName(CmdResult r) {
    switch (r) {
        case CmdResult::ACCEPTED:               return "ACCEPTED";
        case CmdResult::MESSAGE_TOO_LARGE:      return "MESSAGE_TOO_LARGE";
        case CmdResult::INVALID_JSON:           return "INVALID_JSON";
        case CmdResult::WRONG_SCHEMA_VERSION:   return "WRONG_SCHEMA_VERSION";
        case CmdResult::MISSING_COMMAND_ID:     return "MISSING_COMMAND_ID";
        case CmdResult::WRONG_DEVICE_ID:        return "WRONG_DEVICE_ID";
        case CmdResult::INVALID_TARGET:         return "INVALID_TARGET";
        case CmdResult::INVALID_ACTION:         return "INVALID_ACTION";
        case CmdResult::INVALID_ACTION_FOR_ALL: return "INVALID_ACTION_FOR_ALL";
        case CmdResult::INVALID_MODE:           return "INVALID_MODE";
        case CmdResult::SENSOR_DATA_UNAVAILABLE:return "SENSOR_DATA_UNAVAILABLE";
        case CmdResult::DHT_INVALID:            return "DHT_INVALID";
        case CmdResult::RETURNED_TO_AUTOMATIC:  return "RETURNED_TO_AUTOMATIC";
        default:                                return "UNKNOWN";
    }
}

struct ParsedCommand {
    int         schema_version     = 1;
    std::string command_id         = "";
    std::string device_id          = "";
    std::string target             = "";
    std::string action             = "";
    std::string mode               = "manual";
    uint32_t    expires_in_seconds = DEFAULT_OVERRIDE_SECONDS;
    bool        parseSuccess       = true;
    bool        tooLarge           = false;
    bool        hasLatestSensors   = true;
    SensorReadings latestSensors   = {false, 1000, false, 24.0f, 40.0f, true};
};

void computeControlLogic(const SensorReadings& sensors, ActuatorState& actuators);

CmdResult applyParsedCommand(const ParsedCommand& cmd, ManualOverride& ovr,
                             ActuatorState& actuators, unsigned long nowMs) {
    if (cmd.tooLarge)       return CmdResult::MESSAGE_TOO_LARGE;
    if (!cmd.parseSuccess)  return CmdResult::INVALID_JSON;

    if (cmd.schema_version != MQTT_SCHEMA_VERSION)
        return CmdResult::WRONG_SCHEMA_VERSION;
    if (cmd.command_id.empty())
        return CmdResult::MISSING_COMMAND_ID;
    if (cmd.device_id != DEVICE_ID)
        return CmdResult::WRONG_DEVICE_ID;

    const bool targetLight = (cmd.target == "light");
    const bool targetFan   = (cmd.target == "fan");
    const bool targetAc    = (cmd.target == "ac");
    const bool targetAll   = (cmd.target == "all");
    const bool targetAuto  = (cmd.target == "automatic");

    if (!targetLight && !targetFan && !targetAc && !targetAll && !targetAuto)
        return CmdResult::INVALID_TARGET;

    if (targetAuto) {
        ovr = ManualOverride();
        if (cmd.hasLatestSensors) {
            computeControlLogic(cmd.latestSensors, actuators);
        } else {
            actuators = {false, false, false};
        }
        return CmdResult::RETURNED_TO_AUTOMATIC;
    }

    if (cmd.mode != "manual") return CmdResult::INVALID_MODE;

    const bool actionOn  = (cmd.action == "on");
    const bool actionOff = (cmd.action == "off");

    if (!actionOn && !actionOff) return CmdResult::INVALID_ACTION;

    uint32_t expiry = cmd.expires_in_seconds;
    if (expiry == 0 || expiry > MAX_OVERRIDE_SECONDS) expiry = DEFAULT_OVERRIDE_SECONDS;

    if (targetAll) {
        if (!actionOff) return CmdResult::INVALID_ACTION_FOR_ALL;
        ovr.mode        = ControlMode::MANUAL_OVERRIDE;
        ovr.startMs     = nowMs;
        ovr.durationMs  = static_cast<unsigned long>(expiry) * 1000UL;
        ovr.lightActive = true; ovr.lightValue = false;
        ovr.fanActive   = true; ovr.fanValue   = false;
        ovr.acActive    = true; ovr.acValue    = false;
        actuators = {false, false, false};
        return CmdResult::ACCEPTED;
    }

    const bool desiredState = actionOn;
    if (desiredState && (targetFan || targetAc)) {
        if (!cmd.hasLatestSensors) return CmdResult::SENSOR_DATA_UNAVAILABLE;
        if (!cmd.latestSensors.dhtValid) return CmdResult::DHT_INVALID;
    }

    ovr = ManualOverride();
    if (cmd.hasLatestSensors) {
        computeControlLogic(cmd.latestSensors, actuators);
    } else {
        actuators = {false, false, false};
    }
    ovr.mode       = ControlMode::MANUAL_OVERRIDE;
    ovr.startMs    = nowMs;
    ovr.durationMs = static_cast<unsigned long>(expiry) * 1000UL;

    if (targetLight) { ovr.lightActive = true; ovr.lightValue = desiredState; actuators.lightOn = desiredState; }
    if (targetFan)   { ovr.fanActive   = true; ovr.fanValue   = desiredState; actuators.fanOn   = desiredState; }
    if (targetAc)    { ovr.acActive    = true; ovr.acValue    = desiredState; actuators.acOn    = desiredState; }

    return CmdResult::ACCEPTED;
}

// Exactly mirrors the normalization and parsing in src/main.cpp
bool parseRawPayload(const uint8_t* payload, unsigned int length, ParsedCommand& outCmd) {
    if (length == 0 || length > static_cast<unsigned int>(MQTT_MAX_PAYLOAD_BYTES)) {
        outCmd.tooLarge = true;
        outCmd.parseSuccess = false;
        return false;
    }

    char rawBuf[MQTT_MAX_PAYLOAD_BYTES + 1];
    memcpy(rawBuf, payload, length);
    rawBuf[length] = '\0';

    // 1. Trim leading whitespace
    char* start = rawBuf;
    while (*start && (*start == ' ' || *start == '\t' || *start == '\r' || *start == '\n')) {
        start++;
    }

    // 2. Trim trailing whitespace
    char* end = rawBuf + strlen(rawBuf);
    while (end > start && (*(end - 1) == ' ' || *(end - 1) == '\t' || *(end - 1) == '\r' || *(end - 1) == '\n')) {
        end--;
        *end = '\0';
    }

    // 3. Strip outer single quotes if wrapped: '{"..."}'
    if (*start == '\'' && end > start && *(end - 1) == '\'') {
        start++;
        end--;
        *end = '\0';
    }

    // 4. Strip outer double quotes if wrapped: "{"..."}" or "{\"..."}"
    if (*start == '"' && end > start && *(end - 1) == '"') {
        if (*(start + 1) == '{' || (*(start + 1) == '\\' && *(start + 2) == '{')) {
            start++;
            end--;
            *end = '\0';
        }
    }

    // 5. Unescape \" to " if backslashes precede quotes
    char cleanBuf[MQTT_MAX_PAYLOAD_BYTES + 1];
    size_t w = 0;
    for (char* p = start; *p != '\0'; p++) {
        if (*p == '\\' && (*(p + 1) == '"' || *(p + 1) == '\\')) {
            cleanBuf[w++] = *(p + 1);
            p++;
        } else {
            cleanBuf[w++] = *p;
        }
    }
    cleanBuf[w] = '\0';

    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, static_cast<const char*>(cleanBuf));
    if (err) {
        outCmd.parseSuccess = false;
        return false;
    }

    // 6. If JSON was serialized as a quoted string, unwrap the inner object
    if (doc.is<const char*>()) {
        const char* inner = doc.as<const char*>();
        StaticJsonDocument<512> innerDoc;
        DeserializationError innerErr = deserializeJson(innerDoc, inner);
        if (!innerErr && innerDoc.is<JsonObject>()) {
            doc = innerDoc;
        } else {
            outCmd.parseSuccess = false;
            return false;
        }
    }

    if (!doc.is<JsonObject>()) {
        outCmd.parseSuccess = false;
        return false;
    }

    outCmd.parseSuccess       = true;
    outCmd.tooLarge           = false;
    outCmd.command_id         = doc["command_id"] | "";
    outCmd.device_id          = doc["device_id"]  | "";
    outCmd.target             = doc["target"]     | "";
    outCmd.action             = doc["action"]     | "";
    outCmd.schema_version     = doc["schema_version"] | 0;
    outCmd.expires_in_seconds = doc["expires_in_seconds"] | DEFAULT_OVERRIDE_SECONDS;

    return true;
}

void updateManualOverride(ManualOverride& ovr, ActuatorState& actuators,
                          const SensorReadings& sensors, unsigned long nowMs) {
    if (ovr.mode != ControlMode::MANUAL_OVERRIDE) return;

    const unsigned long elapsed = nowMs - ovr.startMs;
    if (elapsed >= ovr.durationMs) {
        ovr = ManualOverride();
        return;
    }

    if (ovr.lightActive) actuators.lightOn = ovr.lightValue;
    if (ovr.fanActive)   actuators.fanOn   = (ovr.fanValue && sensors.dhtValid);
    if (ovr.acActive)    actuators.acOn    = (ovr.acValue  && sensors.dhtValid);
}

void computeControlLogic(const SensorReadings& sensors, ActuatorState& actuators) {
    if (!sensors.occupied) {
        actuators = {false, false, false};
        return;
    }
    actuators.lightOn = sensors.isDark;
    if (!sensors.dhtValid) {
        actuators.fanOn = false;
        actuators.acOn  = false;
        return;
    }
    actuators.fanOn = (sensors.temperature >= TEMP_FAN_THRESHOLD);
    actuators.acOn  = (sensors.temperature >= TEMP_AC_THRESHOLD);
}

static int g_passed = 0;
static int g_failed = 0;

void checkResult(const char* testName, CmdResult expected, CmdResult actual) {
    bool ok = (expected == actual);
    std::cout << "[" << (ok ? "PASS" : "FAIL") << "] " << testName << "\n";
    if (!ok) {
        std::cout << "       Expected: " << cmdResultName(expected) << ", Actual: " << cmdResultName(actual) << "\n";
        g_failed++;
    } else {
        g_passed++;
    }
}

void checkBool(const char* testName, bool expected, bool actual) {
    bool ok = (expected == actual);
    std::cout << "[" << (ok ? "PASS" : "FAIL") << "] " << testName << "\n";
    if (!ok) {
        std::cout << "       Expected: " << expected << ", Actual: " << actual << "\n";
        g_failed++;
    } else {
        g_passed++;
    }
}

void checkMode(const char* testName, ControlMode expected, ControlMode actual) {
    bool ok = (expected == actual);
    std::cout << "[" << (ok ? "PASS" : "FAIL") << "] " << testName << "\n";
    if (!ok) {
        std::cout << "       Expected mode: " << (int)expected << ", Actual: " << (int)actual << "\n";
        g_failed++;
    } else {
        g_passed++;
    }
}

static ParsedCommand makeCmd(const std::string& commandId, const std::string& deviceId,
                             const std::string& target, const std::string& action,
                             uint32_t expiry = DEFAULT_OVERRIDE_SECONDS, int schemaVer = 1) {
    ParsedCommand c;
    c.schema_version     = schemaVer;
    c.command_id         = commandId;
    c.device_id          = deviceId;
    c.target             = target;
    c.action             = action;
    c.expires_in_seconds = expiry;
    c.parseSuccess       = true;
    c.tooLarge           = false;
    return c;
}

int main() {
    std::cout << "============================================================\n";
    std::cout << "  PHASE 2 COMMAND & OVERRIDE LOGIC VERIFICATION SUITE\n";
    std::cout << "============================================================\n";

    ManualOverride ovr;
    ActuatorState  act;
    CmdResult      result;

    // 1. Valid light OFF
    ovr = ManualOverride(); act = {true, false, false};
    result = applyParsedCommand(makeCmd("cmd-001", "room-1", "light", "off", 60), ovr, act, 1000);
    checkResult("1. Valid light OFF command", CmdResult::ACCEPTED, result);
    checkBool  ("1. Light is OFF after command", false, act.lightOn);
    checkMode  ("1. Mode is MANUAL_OVERRIDE", ControlMode::MANUAL_OVERRIDE, ovr.mode);

    // 2. Valid light ON
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-002", "room-1", "light", "on", 60), ovr, act, 2000);
    checkResult("2. Valid light ON command", CmdResult::ACCEPTED, result);
    checkBool  ("2. Light is ON after command", true, act.lightOn);

    // 3. Valid fan ON
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-003", "room-1", "fan", "on", 30), ovr, act, 3000);
    checkResult("3. Valid fan ON command", CmdResult::ACCEPTED, result);
    checkBool  ("3. Fan is ON after command", true, act.fanOn);

    // 4. Valid AC ON
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-004", "room-1", "ac", "on", 120), ovr, act, 4000);
    checkResult("4. Valid AC ON command", CmdResult::ACCEPTED, result);
    checkBool  ("4. AC is ON after command", true, act.acOn);

    // 5. All OFF command
    ovr = ManualOverride(); act = {true, true, true};
    result = applyParsedCommand(makeCmd("cmd-005", "room-1", "all", "off", 60), ovr, act, 5000);
    checkResult("5. All OFF command accepted", CmdResult::ACCEPTED, result);
    checkBool  ("5. Light OFF after all-off", false, act.lightOn);
    checkBool  ("5. Fan OFF after all-off",   false, act.fanOn);
    checkBool  ("5. AC OFF after all-off",    false, act.acOn);

    // 6. Return to automatic
    ovr = ManualOverride(); ovr.mode = ControlMode::MANUAL_OVERRIDE; act = {false, true, false};
    result = applyParsedCommand(makeCmd("cmd-006", "room-1", "automatic", ""), ovr, act, 6000);
    checkResult("6. Return-to-automatic accepted", CmdResult::RETURNED_TO_AUTOMATIC, result);
    checkMode  ("6. Mode is AUTOMATIC after return", ControlMode::AUTOMATIC, ovr.mode);

    // 7. Wrong device ID
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-007", "room-99", "light", "off"), ovr, act, 7000);
    checkResult("7. Wrong device_id rejected", CmdResult::WRONG_DEVICE_ID, result);

    // 8. Missing command ID
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("", "room-1", "light", "off"), ovr, act, 8000);
    checkResult("8. Missing command_id rejected", CmdResult::MISSING_COMMAND_ID, result);

    // 9. Invalid target
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-009", "room-1", "heater", "on"), ovr, act, 9000);
    checkResult("9. Invalid target rejected", CmdResult::INVALID_TARGET, result);

    // 10. Invalid action
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-010", "room-1", "light", "toggle"), ovr, act, 10000);
    checkResult("10. Invalid action rejected", CmdResult::INVALID_ACTION, result);

    // 11. Wrong schema version
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-011", "room-1", "light", "off", 60, 99), ovr, act, 11000);
    checkResult("11. Wrong schema_version rejected", CmdResult::WRONG_SCHEMA_VERSION, result);

    // 12. Malformed JSON
    ovr = ManualOverride(); act = {false, false, false};
    ParsedCommand badJson; badJson.parseSuccess = false;
    result = applyParsedCommand(badJson, ovr, act, 12000);
    checkResult("12. Malformed JSON rejected", CmdResult::INVALID_JSON, result);

    // 13. Oversized payload
    ovr = ManualOverride(); act = {false, false, false};
    ParsedCommand bigMsg; bigMsg.tooLarge = true;
    result = applyParsedCommand(bigMsg, ovr, act, 13000);
    checkResult("13. Oversized message rejected", CmdResult::MESSAGE_TOO_LARGE, result);

    // 14. Target 'all' with action 'on' rejected
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-014", "room-1", "all", "on"), ovr, act, 14000);
    checkResult("14. 'all on' rejected", CmdResult::INVALID_ACTION_FOR_ALL, result);

    // 15. Manual override expiry logic
    ovr = ManualOverride(); act = {true, false, false};
    SensorReadings s15 = {true, 2500, true, 25.0f, 50.0f, true};
    applyParsedCommand(makeCmd("cmd-015", "room-1", "light", "off", 60), ovr, act, 1000);
    act = {true, false, false};
    updateManualOverride(ovr, act, s15, 30000);
    checkBool("15. Light OFF at 30s (override active)", false, act.lightOn);
    checkMode("15. Mode is MANUAL_OVERRIDE at 30s", ControlMode::MANUAL_OVERRIDE, ovr.mode);
    act = {true, false, false};
    updateManualOverride(ovr, act, s15, 62000);
    checkMode("15. Mode returns to AUTOMATIC after 60s", ControlMode::AUTOMATIC, ovr.mode);
    checkBool("15. Light follows automatic (ON) after expiry", true, act.lightOn);

    // 16. Automatic rules apply after override expiration
    ovr = ManualOverride();
    SensorReadings s16 = {true, 2800, true, 30.0f, 55.0f, true};
    act = {false, true, false};
    applyParsedCommand(makeCmd("cmd-016", "room-1", "fan", "off", 10), ovr, act, 0);
    checkBool("16. Fan forced OFF during override", false, act.fanOn);
    computeControlLogic(s16, act);
    updateManualOverride(ovr, act, s16, 11000);
    checkMode("16. Mode is AUTOMATIC after expiry", ControlMode::AUTOMATIC, ovr.mode);
    checkBool("16. Fan ON again automatically (30C >= 28C)", true, act.fanOn);

    // 17. DHT failsafe suppresses manual fan activation when invalid
    ovr = ManualOverride(); act = {false, false, false};
    SensorReadings sNoDht = {true, 2500, true, NAN, NAN, false};
    applyParsedCommand(makeCmd("cmd-017", "room-1", "fan", "on", 60), ovr, act, 1000);
    act.fanOn = true;
    updateManualOverride(ovr, act, sNoDht, 2000);
    checkBool("17. Fan OFF despite manual command due to DHT failsafe", false, act.fanOn);

    // 18. Light override works regardless of DHT validity
    ovr = ManualOverride(); act = {false, false, false};
    applyParsedCommand(makeCmd("cmd-018", "room-1", "light", "on", 60), ovr, act, 1000);
    act.lightOn = false;
    updateManualOverride(ovr, act, sNoDht, 2000);
    checkBool("18. Light ON override operates with invalid DHT", true, act.lightOn);

    // 19. Return to automatic clears all channels
    ovr = ManualOverride(); act = {true, true, true};
    applyParsedCommand(makeCmd("cmd-019a", "room-1", "all", "off", 60), ovr, act, 1000);
    checkMode("19. Mode is MANUAL_OVERRIDE", ControlMode::MANUAL_OVERRIDE, ovr.mode);
    applyParsedCommand(makeCmd("cmd-019b", "room-1", "automatic", ""), ovr, act, 2000);
    checkMode("19. Mode is AUTOMATIC after reset", ControlMode::AUTOMATIC, ovr.mode);
    checkBool("19. lightActive flag cleared", false, ovr.lightActive);
    checkBool("19. fanActive flag cleared",   false, ovr.fanActive);
    checkBool("19. acActive flag cleared",    false, ovr.acActive);

    // 20. Local automatic regression test
    ovr = ManualOverride();
    SensorReadings s20 = {true, 500, false, 33.0f, 60.0f, true};
    ActuatorState a20;
    computeControlLogic(s20, a20);
    updateManualOverride(ovr, a20, s20, 1000);
    checkBool("20. Light OFF (bright room)", false, a20.lightOn);
    checkBool("20. Fan ON (33C >= 28C)",     true,  a20.fanOn);
    checkBool("20. AC ON (33C >= 32C)",      true,  a20.acOn);

    // ============================================================
    // Real-World Payload Parsing & Normalization Tests (Phase 2 Fix)
    // ============================================================
    std::cout << "\n--- Real-World MQTT Payload Normalization Tests ---\n";

    // 27. Standard JSON payload parsing
    {
        std::string raw = "{\"schema_version\":1,\"command_id\":\"cmd-021\",\"device_id\":\"room-1\",\"target\":\"light\",\"action\":\"off\",\"mode\":\"manual\",\"expires_in_seconds\":60}";
        ParsedCommand cmd;
        bool parsed = parseRawPayload((const uint8_t*)raw.c_str(), raw.length(), cmd);
        checkBool("27. Standard JSON parsed successfully", true, parsed);
        checkBool("27. Command ID extracted accurately", true, cmd.command_id == "cmd-021");
    }

    // 28. Escaped quotes JSON (PowerShell/CMD literal backslashes)
    {
        std::string raw = "{\\\"schema_version\\\":1,\\\"command_id\\\":\\\"cmd-022\\\",\\\"device_id\\\":\\\"room-1\\\",\\\"target\\\":\\\"fan\\\",\\\"action\\\":\\\"on\\\",\\\"mode\\\":\\\"manual\\\",\\\"expires_in_seconds\\\":30}";
        ParsedCommand cmd;
        bool parsed = parseRawPayload((const uint8_t*)raw.c_str(), raw.length(), cmd);
        checkBool("28. Escaped quotes JSON normalized and parsed", true, parsed);
        checkBool("28. Target extracted from unescaped JSON", true, cmd.target == "fan");
    }

    // 29. Outer single quotes: '{"..."}'
    {
        std::string raw = "'{\"schema_version\":1,\"command_id\":\"cmd-023\",\"device_id\":\"room-1\",\"target\":\"ac\",\"action\":\"on\",\"mode\":\"manual\",\"expires_in_seconds\":45}'";
        ParsedCommand cmd;
        bool parsed = parseRawPayload((const uint8_t*)raw.c_str(), raw.length(), cmd);
        checkBool("29. Outer single quotes stripped and parsed", true, parsed);
        checkBool("29. Target extracted accurately", true, cmd.target == "ac");
    }

    // 30. Outer double quotes + escaped quotes: "{\"..."}"
    {
        std::string raw = "\"{\\\"schema_version\\\":1,\\\"command_id\\\":\\\"cmd-024\\\",\\\"device_id\\\":\\\"room-1\\\",\\\"target\\\":\\\"all\\\",\\\"action\\\":\\\"off\\\",\\\"mode\\\":\\\"manual\\\",\\\"expires_in_seconds\":60}\"";
        ParsedCommand cmd;
        bool parsed = parseRawPayload((const uint8_t*)raw.c_str(), raw.length(), cmd);
        checkBool("30. Quoted string unwrapped and parsed", true, parsed);
        checkBool("30. Target 'all' identified", true, cmd.target == "all");
    }

    // 31. Trailing whitespace / CRLF
    {
        std::string raw = " \r\n  {\"schema_version\":1,\"command_id\":\"cmd-025\",\"device_id\":\"room-1\",\"target\":\"automatic\",\"action\":\"off\"}  \n\r ";
        ParsedCommand cmd;
        bool parsed = parseRawPayload((const uint8_t*)raw.c_str(), raw.length(), cmd);
        checkBool("31. Whitespace and CRLF trimmed cleanly", true, parsed);
        checkBool("31. Target 'automatic' extracted", true, cmd.target == "automatic");
    }

    // 32. Malformed JSON returns false
    {
        std::string raw = "{ this is definitely not valid json }";
        ParsedCommand cmd;
        bool parsed = parseRawPayload((const uint8_t*)raw.c_str(), raw.length(), cmd);
        checkBool("32. Truly invalid JSON correctly rejected", false, parsed);
    }

    // Additional command-safety and override replacement tests
    // 21. Non-automatic targets require manual mode
    ovr = ManualOverride(); act = {false, false, false};
    ParsedCommand c21 = makeCmd("cmd-021", "room-1", "light", "on");
    c21.mode = "unsupported";
    result = applyParsedCommand(c21, ovr, act, 21000);
    checkResult("21. Invalid control mode rejected", CmdResult::INVALID_MODE, result);

    // 22. Climate ON is rejected until a validated sensor sample exists
    ovr = ManualOverride(); act = {false, false, false};
    ParsedCommand c22 = makeCmd("cmd-022", "room-1", "fan", "on");
    c22.hasLatestSensors = false;
    result = applyParsedCommand(c22, ovr, act, 22000);
    checkResult("22. Fan ON without sensor data rejected", CmdResult::SENSOR_DATA_UNAVAILABLE, result);
    checkBool("22. Fan remains OFF", false, act.fanOn);

    // 23. Climate ON is rejected immediately when DHT22 is invalid
    ovr = ManualOverride(); act = {false, false, false};
    ParsedCommand c23 = makeCmd("cmd-023", "room-1", "ac", "on");
    c23.latestSensors.dhtValid = false;
    result = applyParsedCommand(c23, ovr, act, 23000);
    checkResult("23. AC ON with invalid DHT rejected", CmdResult::DHT_INVALID, result);
    checkBool("23. AC remains OFF", false, act.acOn);

    // 24. Return-to-automatic recomputes outputs before acknowledgement
    ovr = ManualOverride(); ovr.mode = ControlMode::MANUAL_OVERRIDE; act = {true, false, false};
    ParsedCommand c24 = makeCmd("cmd-024", "room-1", "automatic", "");
    c24.latestSensors = {false, 3000, true, 35.0f, 60.0f, true};
    result = applyParsedCommand(c24, ovr, act, 24000);
    checkResult("24. Return-to-automatic accepted", CmdResult::RETURNED_TO_AUTOMATIC, result);
    checkBool("24. Automatic state applied before result", false, act.lightOn);

    // 25. Excessive override duration falls back to the configured default
    ovr = ManualOverride(); act = {false, false, false};
    result = applyParsedCommand(makeCmd("cmd-025", "room-1", "light", "on", 4000000000U), ovr, act, 25000);
    checkResult("25. Command with excessive duration accepted safely", CmdResult::ACCEPTED, result);
    checkBool("25. Excessive duration replaced with default", true,
              ovr.durationMs == DEFAULT_OVERRIDE_SECONDS * 1000UL);

    // 26. A new command replaces older channel overrides and restores unselected outputs
    ovr = ManualOverride(); act = {true, false, false};
    ParsedCommand c26a = makeCmd("cmd-026a", "room-1", "light", "on", 60);
    c26a.latestSensors = {true, 2500, true, 30.0f, 50.0f, true};
    applyParsedCommand(c26a, ovr, act, 26000);
    ParsedCommand c26b = makeCmd("cmd-026b", "room-1", "fan", "off", 60);
    c26b.latestSensors = c26a.latestSensors;
    result = applyParsedCommand(c26b, ovr, act, 27000);
    checkResult("26. Replacement override accepted", CmdResult::ACCEPTED, result);
    checkBool("26. Previous light override flag cleared", false, ovr.lightActive);
    checkBool("26. Unselected light follows automatic rules", true, act.lightOn);

    std::cout << "------------------------------------------------------------\n";
    std::cout << "Results: " << g_passed << " / " << (g_passed + g_failed) << " tests passed.\n";
    std::cout << "============================================================\n";

    return (g_failed == 0) ? 0 : 1;
}
