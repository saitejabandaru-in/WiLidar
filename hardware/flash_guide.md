# ESP32-S3 Firmware Flashing Guide

This directory contains the firmware for **WiLidar** nodes running on the ESP32-S3 development board (specifically optimized for `ESP32-S3-DevKitC-1 N8R8`).

Follow these steps to configure, build, and flash your nodes.

---

## 1. Prerequisites

1. **Hardware**: ESP32-S3 development board (N8R8 variant recommended).
2. **Cables**: High-quality USB-C data cable.
3. **ESP-IDF Toolchain**: Version 5.3+ (NOT Arduino).

### Installing ESP-IDF v5.3 (Mac / Linux)

```bash
# Clone the ESP-IDF repository recursively
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
git checkout v5.3
./install.sh esp32s3
source export.sh
```

---

## 2. Configuration

Before building the firmware, edit [config.h](file:///Users/saitejabandaru/.gemini/antigravity/scratch/wilidar/hardware/esp32s3/main/config.h) to configure your network settings:

1. Open `hardware/esp32s3/main/config.h` in your editor.
2. Modify the following parameters:
   - `WIFI_SSID`: Set to your dedicated router SSID.
   - `WIFI_PASS`: Set to your router password.
   - `SERVER_IP`: Set to the static IP address of your Python receiver server (e.g. Raspberry Pi 5).
   - `NODE_ID`: Assign a unique 32-bit integer per node (e.g. `1001` for room corner, `1002` for hallway).

---

## 3. Build & Flash

Run these commands from the `hardware/esp32s3` directory:

```bash
# Set target microcontroller to ESP32-S3
idf.py set-target esp32s3

# Build the project
idf.py build

# Flash the firmware and monitor serial output
# (Replace /dev/ttyUSB0 with your actual USB port, e.g. /dev/cu.usbserial-XXX on Mac)
idf.py -p /dev/ttyUSB0 flash monitor
```

---

## 4. Status Indicator LED (WS2812) Reference

The onboard LED reflects the operational state of the firmware:

- 🔵 **BLUE** (Blinking): Booting and attempting connection to the WiFi AP.
- 🟢 **GREEN** (Solid): Successfully connected, collecting CSI, and pipeline active.
- 🔴 **RED** (Solid/Blinking): Critical error (WiFi connection lost, or internal processing queue overflow).
- 🟣 **PURPLE** (Pulse): Normal operation, heartbeat telemetry being transmitted to the server.
