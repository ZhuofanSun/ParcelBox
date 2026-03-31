# ParcelBox

ParcelBox is a Raspberry Pi smart parcel box prototype. It combines RFID access
control, a pan-tilt camera, face detection and tracking, occupancy sensing,
local alerts, SQLite storage, and a browser dashboard into one device-side
system for residential package monitoring.

## Team

- Zhuofan Sun - GitHub: [ZhuofanSun](https://github.com/ZhuofanSun)
- Jiayin Chen - GitHub: [Yinnc259](https://github.com/Yinnc259)
- Yangfei Wang - GitHub: [stayinnight1](https://github.com/stayinnight1)

## What the project does

- Enrolls and authorizes RFID cards with local access rules
- Opens and closes the locker with a servo-based lock and auto-close timer
- Streams live camera video to the browser with a WebSocket vision overlay
- Detects and tracks faces with a pan-tilt camera mount
- Captures snapshots on manual, RFID, button, and near-face events
- Detects locker occupancy with an ultrasonic sensor
- Stores events, snapshots, cards, and settings in local SQLite storage
- Provides a web console for monitoring, control, debugging, and settings

## Tech stack

- Raspberry Pi
- FastAPI + Uvicorn
- OpenCV + Picamera2
- SQLite
- HTML, CSS, and vanilla JavaScript
- PN532 RFID reader
- OV5647 camera
- Servo motors, ultrasonic sensor, button, buzzer, and RGB LED

## Repository layout

- `main.py` - application entry point and service wiring
- `config.py` - device pins and runtime configuration
- `services/` - business logic and long-running workers
- `web/` - HTTP and WebSocket routes
- `data/` - SQLite schema and persistence layer
- `drivers/` - hardware access wrappers
- `frontend/` - static dashboard served by FastAPI
- `scripts/hardware_smoke_test.py` - quick hardware validation

## What you need before running

- Raspberry Pi OS with camera and GPIO access enabled
- The hardware wired to match `config.py`
- Python 3 with virtual environment support
- `pigpiod` available for servo control

Install the Raspberry Pi system packages:

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv pigpio-tools python3-pigpio
```

Create the virtual environment and install Python dependencies:

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
```

`--system-site-packages` is required so the virtual environment can use the
system-installed `Picamera2` package.

## Quick start

1. Review `config.py` and confirm the GPIO pins, camera settings, and email
   defaults match your hardware.
2. Start the servo daemon:

   ```bash
   sudo systemctl enable --now pigpiod
   ```

3. Optionally run a hardware smoke test:

   ```bash
   ./.venv/bin/python scripts/hardware_smoke_test.py all
   ```

4. Start the application:

   ```bash
   ./.venv/bin/python main.py
   ```

5. Open the dashboard in a browser:

   - `http://raspberrypi.local:8000`
   - `http://<pi-lan-ip>:8000`

## Runtime notes

- The frontend is served directly by FastAPI. There is no separate frontend
  build step.
- Data is stored locally in `iot_locker.db`.
- Snapshot images are stored under `data/snapshots/`.
- Profile and email settings are managed from the dashboard and persisted in
  SQLite.

## Project scope

- Single-device prototype only
- Local dashboard, not a cloud platform
- Face detection and tracking only, not face recognition
- MJPEG plus WebSocket instead of WebRTC or H.264

## Suggested reading order

If you want to understand the project quickly, read the files in this order:

1. `README.md`
2. `main.py`
3. `config.py`
4. `services/locker_service.py`
5. `services/access_service.py`
6. `services/camera_service.py`
7. `services/vision_service.py`
8. `data/event_store.py`
9. `web/routes_*.py`
10. `frontend/scripts/app.js`
