#include <cmath>
#include <cstdint>
#include <iostream>

constexpr float SUPPLY_VOLTAGE_V = 230.0f;
constexpr float LIGHT_RATED_POWER_W = 20.0f;
constexpr float FAN_RATED_POWER_W = 75.0f;
constexpr float AC_RATED_POWER_W = 1500.0f;
constexpr float CURRENT_SENSOR_MAX_A = 10.0f;
constexpr float ENERGY_TARIFF_INR_PER_KWH = 8.0f;
constexpr float HIGH_POWER_THRESHOLD_W = 1800.0f;
constexpr float UNOCCUPIED_POWER_THRESHOLD_W = 10.0f;

struct Actuators { bool light; bool fan; bool ac; };
struct EnergyState {
    double energyWh = 0.0;
    uint32_t lastMs = 0;
    bool hasSample = false;
};
struct Metrics {
    float modeledPowerW;
    float sensorCurrentA;
    float currentA;
    float powerW;
    double energyWh;
    double costInr;
    bool highPower;
    bool unoccupiedPower;
};

Metrics calculate(bool occupied, Actuators a, int raw, uint32_t now, EnergyState &state) {
    float modeled = (a.light ? LIGHT_RATED_POWER_W : 0.0f) +
                    (a.fan ? FAN_RATED_POWER_W : 0.0f) +
                    (a.ac ? AC_RATED_POWER_W : 0.0f);
    float sensorA = (static_cast<float>(raw) / 4095.0f) * CURRENT_SENSOR_MAX_A;
    float sensorW = sensorA * SUPPLY_VOLTAGE_V;
    float power = modeled > sensorW ? modeled : sensorW;
    if (state.hasSample) {
        uint32_t elapsed = now - state.lastMs;
        state.energyWh += static_cast<double>(power) * elapsed / 3600000.0;
    }
    state.lastMs = now;
    state.hasSample = true;
    return {modeled, sensorA, power / SUPPLY_VOLTAGE_V, power, state.energyWh,
            state.energyWh / 1000.0 * ENERGY_TARIFF_INR_PER_KWH,
            power >= HIGH_POWER_THRESHOLD_W,
            !occupied && power >= UNOCCUPIED_POWER_THRESHOLD_W};
}

int passed = 0;
int failed = 0;
void check(const char *name, bool ok) {
    std::cout << (ok ? "[PASS] " : "[FAIL] ") << name << "\n";
    ok ? ++passed : ++failed;
}
bool near(double actual, double expected, double tolerance = 0.01) {
    return std::fabs(actual - expected) <= tolerance;
}

int main() {
    std::cout << "============================================================\n";
    std::cout << "  PHASE 3 POWER, ENERGY & ALERT VERIFICATION SUITE\n";
    std::cout << "============================================================\n";

    EnergyState s1;
    auto m = calculate(true, {false, false, false}, 0, 0, s1);
    check("1. All loads OFF produce 0 W", near(m.powerW, 0));
    check("2. Light model is 20 W", near(calculate(true, {true, false, false}, 0, 1, s1).modeledPowerW, 20));
    check("3. Fan model is 75 W", near(calculate(true, {false, true, false}, 0, 2, s1).modeledPowerW, 75));
    check("4. AC model is 1500 W", near(calculate(true, {false, false, true}, 0, 3, s1).modeledPowerW, 1500));
    check("5. Combined model is 1595 W", near(calculate(true, {true, true, true}, 0, 4, s1).modeledPowerW, 1595));

    EnergyState s2;
    m = calculate(true, {false, false, false}, 2048, 0, s2);
    check("6. Mid-scale sensor represents about 5 A", near(m.sensorCurrentA, 5.001, 0.01));
    check("7. Sensor can simulate about 1150 W", near(m.powerW, 1150.28, 0.5));

    EnergyState s3;
    m = calculate(true, {false, false, true}, 100, 0, s3);
    check("8. Load model wins over a lower sensor value", near(m.powerW, 1500));
    check("9. Current is derived from selected power", near(m.currentA, 1500.0 / 230.0, 0.01));

    EnergyState s4;
    calculate(true, {false, false, false}, 0, 1000, s4);
    m = calculate(true, {true, false, false}, 0, 3601000, s4);
    check("10. 20 W for one hour accumulates 20 Wh", near(m.energyWh, 20));
    check("11. Cost is calculated from kWh and tariff", near(m.costInr, 0.16));

    EnergyState s5;
    calculate(true, {false, false, false}, 0, 0, s5);
    m = calculate(true, {false, false, false}, 0, 3600000, s5);
    check("12. Energy does not increase when power is zero", near(m.energyWh, 0));

    EnergyState s6;
    calculate(true, {false, false, false}, 0, UINT32_MAX - 999, s6);
    m = calculate(true, {true, false, false}, 0, 1000, s6);
    check("13. Unsigned elapsed time survives millis rollover", near(m.energyWh, 20.0 * 2000.0 / 3600000.0, 0.0001));

    EnergyState s7;
    m = calculate(true, {false, false, false}, 4095, 0, s7);
    check("14. Full-scale current sensor is 10 A", near(m.sensorCurrentA, 10));
    check("15. Full-scale power is 2300 W", near(m.powerW, 2300));
    check("16. 2300 W raises a high-power alert", m.highPower);
    check("17. Occupied room does not raise empty-room alert", !m.unoccupiedPower);

    EnergyState s8;
    m = calculate(false, {true, false, false}, 0, 0, s8);
    check("18. Power in an empty room raises an alert", m.unoccupiedPower);
    check("19. Empty room with zero power has no alert", !calculate(false, {false, false, false}, 0, 1, s8).unoccupiedPower);
    check("20. Normal 1595 W load stays below high-power threshold",
          !calculate(true, {true, true, true}, 0, 2, s8).highPower);

    std::cout << "------------------------------------------------------------\n";
    std::cout << "Results: " << passed << " / " << (passed + failed) << " tests passed.\n";
    return failed == 0 ? 0 : 1;
}
