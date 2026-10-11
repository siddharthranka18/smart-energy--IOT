# Smart Energy Management System

An IoT-based energy management prototype using ESP32, Wokwi simulation, and PlatformIO. The current version contains a basic ESP32 firmware and LED simulation. Sensors, backend, and dashboard will be added in later stages.

## Setup Instructions

### 1. Prerequisites
- [Git](https://git-scm.com/downloads)
- [Antigravity IDE](https://antigravity.google/) or a compatible VS Code-based IDE
- [PlatformIO IDE extension](https://platformio.org/install/ide)
- [Wokwi Simulator extension](https://marketplace.visualstudio.com/items?itemName=Wokwi.wokwi-vscode)
- A valid Wokwi license if prompted

### 2. Clone the Repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd smart-energy-management
```

### 3. Build the Firmware

Open the project folder in your IDE and run this command in the terminal:

```bash
pio run
```

### 4. Run the Wokwi Simulation

Open `diagram.json` in the IDE and start the simulation using the green **Play** button. The project uses `wokwi.toml` to locate the compiled ESP32 firmware.

**Note:** The current prototype is a simulation. It does not measure real electrical power or control physical appliances.

## Project Status

- [x] ESP32 firmware build
- [x] Basic LED simulation
- [ ] Sensor integration
- [ ] MQTT communication
- [ ] Python backend and database
- [ ] Web dashboard

