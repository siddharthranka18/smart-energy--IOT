/**
 * ============================================================================
 * Verification Test Suite: Phase 1 Decision & Control Logic
 * Description: Validates deterministic state transitions, boundary conditions,
 *              and failsafe behaviors for Phase 1 firmware.
 * ============================================================================
 */

#include <iostream>
#include <cmath>
#include <cassert>
#include <iomanip>
#include <vector>
#include <string>

// Replicate constants and logic from src/main.cpp
constexpr int   LDR_DARK_THRESHOLD   = 2000;
constexpr float TEMP_FAN_THRESHOLD   = 28.0f;
constexpr float TEMP_AC_THRESHOLD    = 32.0f;

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
        actuators.fanOn = false;
        actuators.acOn  = false;
        return;
    }

    // Rule 3: Primary Stage Ventilation / Fan Control
    actuators.fanOn = (sensors.temperature >= TEMP_FAN_THRESHOLD);

    // Rule 4: Secondary Stage Active Refrigeration / AC Control
    actuators.acOn = (sensors.temperature >= TEMP_AC_THRESHOLD);
}

struct TestCase {
    std::string name;
    SensorReadings input;
    ActuatorState expected;
};

int main() {
    std::cout << "============================================================\n";
    std::cout << "  RUNNING PHASE 1 AUTOMATED LOGIC VERIFICATION SUITE\n";
    std::cout << "============================================================\n";

    std::vector<TestCase> testCases = {
        {
            "1. Empty Room (Unoccupied, Dark, Cold)",
            {false, 3000, true, 20.0f, 50.0f, true},
            {false, false, false}
        },
        {
            "2. Empty Room (Unoccupied, Hot 35C, Dark)",
            {false, 3500, true, 35.0f, 60.0f, true},
            {false, false, false}
        },
        {
            "3. Occupied & Bright Room (Comfort 25C)",
            {true, 500, false, 25.0f, 50.0f, true},
            {false, false, false}
        },
        {
            "4. Occupied & Dark Room (Comfort 25C)",
            {true, 2500, true, 25.0f, 50.0f, true},
            {true, false, false}
        },
        {
            "5. Occupied Room at 27.9C (Boundary: Temp < 28C)",
            {true, 500, false, 27.9f, 50.0f, true},
            {false, false, false}
        },
        {
            "6. Occupied Room at 28.0C (Boundary: Fan Trigger)",
            {true, 500, false, 28.0f, 50.0f, true},
            {false, true, false}
        },
        {
            "7. Occupied Room at 30.0C (Fan ON, AC OFF)",
            {true, 500, false, 30.0f, 50.0f, true},
            {false, true, false}
        },
        {
            "8. Occupied Room at 31.9C (Boundary: AC still OFF)",
            {true, 500, false, 31.9f, 50.0f, true},
            {false, true, false}
        },
        {
            "9. Occupied Room at 32.0C (Boundary: AC Trigger)",
            {true, 500, false, 32.0f, 50.0f, true},
            {false, true, true}
        },
        {
            "10. Occupied Room at 35.0C & Dark (Light ON, Fan ON, AC ON)",
            {true, 2800, true, 35.0f, 65.0f, true},
            {true, true, true}
        },
        {
            "11. Failsafe: DHT22 NaN / Invalid Read (Occupied & Dark)",
            {true, 2800, true, NAN, NAN, false},
            {true, false, false}
        },
        {
            "12. Failsafe: DHT22 NaN / Invalid Read (Occupied & Bright)",
            {true, 500, false, NAN, NAN, false},
            {false, false, false}
        }
    };

    int passed = 0;
    for (const auto &tc : testCases) {
        ActuatorState result;
        computeControlLogic(tc.input, result);

        bool pass = (result.lightOn == tc.expected.lightOn) &&
                    (result.fanOn   == tc.expected.fanOn) &&
                    (result.acOn    == tc.expected.acOn);

        std::cout << "[" << (pass ? "PASS" : "FAIL") << "] " << tc.name << "\n";
        std::cout << "       Expected: Light=" << tc.expected.lightOn
                  << ", Fan=" << tc.expected.fanOn
                  << ", AC=" << tc.expected.acOn << "\n";
        std::cout << "       Actual  : Light=" << result.lightOn
                  << ", Fan=" << result.fanOn
                  << ", AC=" << result.acOn << "\n";

        if (pass) {
            passed++;
        }
    }

    std::cout << "------------------------------------------------------------\n";
    std::cout << "Results: " << passed << " / " << testCases.size() << " tests passed.\n";
    std::cout << "============================================================\n";

    return (passed == static_cast<int>(testCases.size())) ? 0 : 1;
}
