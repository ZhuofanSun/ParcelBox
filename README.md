# ParcelBox / IOT Locker

Single-device Raspberry Pi parcel locker prototype for hardware testing, backend validation, and frontend operations-console work.

## Current Status

- [x] RFID card enrollment and permission-based access control
- [x] Door servo open / close workflow with auto-close
- [x] CSI camera MJPEG live stream
- [x] WebSocket face-box overlay, face tracking, standby, and recovery search
- [x] Snapshots from manual trigger, RFID scans, button presses, and close-range face events
- [x] Snapshot pruning with database/file reconciliation
- [x] Ultrasonic occupancy sensing
- [x] Hardware request button with email notification
- [x] Buzzer alarm rules and notification-bell integration
- [x] RGB LED status behavior
- [x] SQLite-backed event store and device settings
- [x] Frontend operations console with Overview / Cards & Access / Events & Snapshots / Debug / Data / Settings
- [x] Theme toggle, profile settings, persistent avatar, email delivery schemes
- [x] Snapshot viewer modal from frontend events and snapshot cards
- [ ] `systemd` startup service and autostart polish
- [ ] Long real-device soak test
- [ ] Ultrasonic threshold calibration on the real locker body

## Project Positioning

- [x] Single-device deployment only
- [x] No multi-user auth, login, register, or logout flow
- [x] Frontend is an operations / testing console, not a polished end-user product site
- [x] `Tabler` is only used as layout and component inspiration; business frontend code stays in `frontend/`
- [x] Vision scope is face detection only, not face recognition

## Hardware Baseline

### Modules

- `PN532` RFID reader over `I2C`
- `OV5647` CSI camera
- `Servo x3`: 1 door servo, 2 camera mount servos
- `Ultrasonic sensor` for occupancy
- `Button` for hardware open-request flow
- `Buzzer` for local prompts and alarms
- `RGB LED` for runtime state indication

### GPIO Baseline

| Module | Pin |
| --- | --- |
| Door servo | `GPIO18` |
| Camera pan servo | `GPIO13` |
| Camera tilt servo | `GPIO12` |
| Button | `GPIO27` |
| Buzzer | `GPIO25` |
| RGB red | `GPIO5` |
| RGB green | `GPIO6` |
| RGB blue | `GPIO26` |
| Ultrasonic trigger | `GPIO16` |
| Ultrasonic echo | `GPIO20` |
| PN532 SDA | `GPIO2` |
| PN532 SCL | `GPIO3` |

Current wiring references:

- `docs/reference/wire.pdf`
- `docs/reference/wire_schem.pdf`
- `docs/reference/wire.fzz`

## Software Baseline

- Platform: Raspberry Pi
- Python: `3.13`
- Camera stack: `Picamera2`
- Vision stack: `OpenCV`
- Servo backend: `pigpio` preferred, `RPi.GPIO` fallback
- RFID stack: `PN532` over `I2C`
- Database: SQLite

## Repo Layout

- `main.py`: app entrypoint and service wiring
- `config.py`: runtime baseline configuration
- `services/`: hardware and business services
- `web/`: FastAPI routes and schemas
- `frontend/`: operations console
- `data/`: SQLite schema, event store, snapshots, and device assets
- `docs/reference/`: wiring / ERD reference material
- `scripts/`: smoke tests and maintenance helpers
- `tests/`: unit tests

## Install

System packages on Raspberry Pi:

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv pigpio-tools python3-pigpio
```

Python environment:

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
```

`--system-site-packages` is required so the venv can see the `apt`-installed Picamera2 package.

## Run

Enable `pigpiod`:

```bash
sudo systemctl enable --now pigpiod
```

Start the app:

```bash
./.venv/bin/python main.py
```

Open one of:

- `http://raspberrypi.local:8000`
- `http://<pi-lan-ip>:8000`

## Useful Smoke Tests

Camera-only smoke test:

```bash
./.venv/bin/python scripts/hardware_smoke_test.py camera
```

Quick camera baseline outside the app:

```bash
rpicam-hello --list-cameras
rpicam-hello -t 3000
rpicam-still -o /tmp/cam.jpg
```

Integrated business checklist:

- [docs/business_test_checklist.md](/Users/sunzhuofan/IOT-project/docs/business_test_checklist.md)

5-minute demo route:

- [docs/demo_runbook_5min.md](/Users/sunzhuofan/IOT-project/docs/demo_runbook_5min.md)

## Runtime Notes

- The frontend now actively reconnects the MJPEG stream on first-load failure.
- Opening the top-right notification bell marks current alerts as read and silences active buzzer alarms.
- Button-triggered emails have their own duplicate-send cooldown.
- Rapid button presses have separate snapshot and in-app-notification cooldowns, but burst-alarm counting is not cooled down.
- Unauthorized RFID scans and button-burst alarms can trigger one search sweep when no face is present; search is not stacked while one is already running.

## Storage

- Main database: `sqlite:///iot_locker.db`
- Snapshots: `data/snapshots`
- Profile avatar: `data/assets`
- Email schemes and device profile: SQLite

Snapshot retention:

- Keep up to `100` snapshot files
- When over limit, delete the oldest `50`
- Database rows are reconciled against disk on startup and during runtime reads

## Frontend Summary

- `Overview`: live stream, high-frequency controls, runtime summary
- `Cards & Access`: stored RFID cards and recent authorization history
- `Events & Snapshots`: event feed and image viewer
- `Debug / Data`: raw table views
- `Settings`: profile, in-app alerts, email schemes

Frontend code is split into:

- `frontend/styles/`
- `frontend/scripts/`

## Main APIs

- `GET /api/locker/status`
- `GET /api/logs/events`
- `GET /api/logs/tables`
- `GET /api/system/status`
- `GET /api/snapshots/{id}`
- `GET /api/snapshots/{id}/file`
- `POST /api/camera/snapshot`
- `POST /api/alerts/silence`
- `GET /api/settings/profile`
- `GET /api/settings/email`

## Email Configuration Model

- SMTP host / port / TLS / timeout / frontend URL / subject / message remain in `config.py`
- User-editable delivery schemes live in SQLite
- Each scheme stores:
  - `name`
  - `enabled`
  - `username`
  - `password`
  - `from_address`
  - multiple recipient emails

## Known Constraints

- No auth layer
- No public-network hardening by default
- MJPEG is still the current stream transport; no WebRTC / H.264 path yet
- Ultrasonic thresholds are still baseline values and need real-box calibration
