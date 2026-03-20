# IOT Locker

Raspberry Pi based smart locker prototype for a parcel locker scenario.

## Project Summary

The project simulates a parcel locker workflow with:

- RFID-based door access and card permission management
- A servo-driven locker door
- A CSI camera with a continuous video stream
- Vision-based human / face detection
- Clear-frame capture and event-linked snapshots
- An ultrasonic sensor for in-box occupancy detection
- A web dashboard for monitoring and control

## Hardware Summary

- `RC522`: read / write RFID cards, card enrollment, permission-based door access
- `Servo x3`: 1 for door open / close, 2 for camera pan / tilt
- `CSI camera`: OV5647, 5MP, max `2592x1944`, wide-angle lens
- `Ultrasonic sensor`: only used to detect whether the locker contains something
- `Button`: external request button for delivery flow
- `Buzzer`: local and remote alarm output
- `RGB LED`: status indicator

## Wiring Sources

Current wiring references in the repo:

- [wire.pdf](/Users/sunzhuofan/IOT-project/wire.pdf)
- [wire_schem.pdf](/Users/sunzhuofan/IOT-project/wire_schem.pdf)
- [wire.fzz](/Users/sunzhuofan/IOT-project/wire.fzz)

These, together with [config.py](/Users/sunzhuofan/IOT-project/config.py), are the current baseline wiring sources.

## Environment Baseline

- Platform: Raspberry Pi
- Language: Python
- Python version: `3.11.2`
- Camera stack: CSI camera with `Picamera2`
- GPIO library: `RPi.GPIO`
- RFID stack: `pi-rc522` + `spidev`

## Dependency Strategy

Use `apt` for Raspberry Pi system packages that integrate with the camera stack:

```bash
sudo apt update
sudo apt install -y python3-picamera2
```

Install OpenCV on the Raspberry Pi when you start the vision pipeline:

```bash
sudo apt install -y python3-opencv
```

Use `pip` / `requirements.txt` for project-level Python packages:

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
```

The `--system-site-packages` flag is important so the virtual environment can see `python3-picamera2` installed by `apt`.

## Raspberry Pi Runtime

- Current Raspberry Pi Python environment: `/home/sunzhuofan/Desktop/ParcelBox/.venv/bin/python`
- Example smoke test command on the Pi:

```bash
/home/sunzhuofan/Desktop/ParcelBox/.venv/bin/python scripts/hardware_smoke_test.py camera
```

- Example Phase 2 demo command on the Pi:

```bash
/home/sunzhuofan/Desktop/ParcelBox/.venv/bin/python main.py
```

Then open:

- [http://raspberrypi.local:8000](http://raspberrypi.local:8000)

## Configuration Baseline

A centralized config template now exists in [config.py](/Users/sunzhuofan/IOT-project/config.py).

It already includes placeholders for:

- GPIO pin assignments
- camera defaults
- camera mount home angles
- ultrasonic thresholds
- storage path / database URL

Known baseline values have been filled in `config.py`. GPIO assignments are now present there and should be treated as the current baseline until hardware verification says otherwise.

Current storage baseline:

- Local SQLite database via `sqlite:///iot_locker.db`
- Snapshot directory at `data/snapshots`

## Hardware Inputs Still Needed

These still need direct hardware confirmation or measurement:

- ultrasonic empty / occupied threshold calibration
- camera mount home angle calibration

## GPIO Baseline

Current GPIO baseline from [config.py](/Users/sunzhuofan/IOT-project/config.py), matching the current `wire*` files:

- `RC522 RST`: `GPIO25`
- `Door servo`: `GPIO18`
- `Camera pan servo`: `GPIO24`
- `Camera tilt servo`: `GPIO23`
- `Button`: `GPIO27`
- `Buzzer`: `GPIO12`
- `RGB LED Red`: `GPIO13`
- `RGB LED Green`: `GPIO19`
- `RGB LED Blue`: `GPIO26`
- `Ultrasonic trigger`: `GPIO16`
- `Ultrasonic echo`: `GPIO20`

## Current Frontend Direction

- Show a continuous live video stream
- Current demo keeps frontend display at `1280x720` for smoother delivery on Raspberry Pi
- Draw detection boxes on the frontend using backend-provided box data
- Provide manual snapshot capture
- Provide card management, device testing, alarm, and log viewing
- Provide camera pan / tilt / home controls
- Provide RGB LED state control
- Provide a limited set of video settings:
  - resolution
  - frame rate
  - brightness
  - sharpness
  - saturation
- Persist video settings and restore them on next startup

## Current Phase 2 Demo

- `main.py` starts a minimal FastAPI app
- `frontend/index.html` shows the live stream and draws boxes on a canvas overlay
- `/api/stream.mjpg` provides the MJPEG stream
- `/api/vision/boxes` currently returns fake backend boxes for overlay validation
- `/api/stream/meta` returns stream and detection sizes
- Current demo defaults: `720p`, `30 fps` stream, `5 fps` boxes polling, JPEG quality `70`
- The MJPEG stream now uses one shared cached JPEG frame for all clients instead of
  re-capturing and re-encoding per viewer
- `CameraService` now recreates the camera cleanly after stop / start

## Vision Baseline

- Current demo uses a `1280x720` stream for frontend display
- Use a separate `640x480` inference resolution for vision tasks
- Use person detection at longer distance
- Only switch to face detection when the target is near enough
- Save clear snapshots from the higher-quality camera output, not from the low-resolution inference frames

## Module Boundaries

### `drivers/`

Direct hardware access only.

- No business logic
- No HTTP
- No database logic
- Keep APIs simple and device-focused

Examples:

- `RC522Reader.read_uid_hex()`
- `Servo.set_angle()`
- `CsiCamera.capture_frame()`
- `UltrasonicSensor.measure_distance_cm()`

### `services/access_service.py`

RFID and permission logic only.

- card enrollment
- card naming
- user binding
- access permission rules
- time-based access checks

### `services/locker_service.py`

Locker workflow orchestration.

- open / close door flow
- bind access result to door events
- trigger occupancy check after close
- link snapshots to door events

### `services/camera_service.py`

Camera device orchestration.

- stream lifecycle
- camera parameter changes
- parameter persistence
- raw snapshot capture
- JPEG encoding for MJPEG output
- shared cached JPEG frame for multiple viewers

### `services/vision_service.py`

Vision understanding only.

- person detection
- face detection
- tracking target state
- clear-frame scoring
- output boxes and tracking data

Current implementation note:

- Phase 2 currently uses a fake moving box so the frontend overlay pipeline can be validated before a real detector is added
- Fake box coordinates now read the current configured stream size each time, so later stream-size changes will not require a process restart

### `services/camera_mount_service.py`

Pan / tilt servo orchestration for the camera mount.

- standby angles
- target tracking
- search pattern when door opens and no face is found
- return-to-home behavior

### `services/occupancy_service.py`

Locker occupancy logic based on ultrasonic readings.

- distance sampling
- average calculation
- empty / occupied classification
- threshold calibration

### `services/alert_service.py`

Local status feedback.

- button event handling
- buzzer states
- RGB LED states
- remote alarm trigger

### `web/`

API and real-time outputs only.

- no direct GPIO access
- no direct database writes outside services
- call services and return structured responses

Recommended split:

- `routes_control.py`
- `routes_stream.py`
- `routes_cards.py`
- `routes_logs.py`
- `routes_settings.py`
- `schemas.py`

### `storage/`

Persistence layer only.

- database connection
- models
- repositories

Suggested initial entities:

- users
- cards
- card_user_bindings
- card_access_rules
- enrollments
- door_events
- snapshots
- snapshot_event_links
- video_settings
- camera_mount_settings
- occupancy_settings
- alarm_events

## Suggested Structure

```text
iot_locker/
├─ README.md
├─ TODO.md
├─ requirements.txt
├─ main.py
├─ config.py
├─ drivers/
│  ├─ rc522.py
│  ├─ servo.py
│  ├─ button.py
│  ├─ ultrasonic_sensor.py
│  ├─ buzzer.py
│  ├─ rgb_led.py
│  └─ camera.py
├─ services/
│  ├─ access_service.py
│  ├─ locker_service.py
│  ├─ camera_service.py
│  ├─ vision_service.py
│  ├─ camera_mount_service.py
│  ├─ occupancy_service.py
│  └─ alert_service.py
├─ web/
│  ├─ routes_control.py
│  ├─ routes_stream.py
│  ├─ routes_cards.py
│  ├─ routes_logs.py
│  ├─ routes_settings.py
│  └─ schemas.py
├─ storage/
│  ├─ db.py
│  ├─ models.py
│  └─ repositories.py
├─ frontend/
│  ├─ package.json
│  └─ src/
│     ├─ pages/
│     ├─ components/
│     ├─ api/
│     ├─ hooks/
│     ├─ store/
│     └─ types/
└─ scripts/
   └─ hardware_smoke_test.py
```

## Core Runtime Flows

### Access Flow

`RC522 -> access_service -> locker_service -> servo -> storage`

### Vision Flow

`camera -> vision_service -> camera_mount_service -> frontend overlays / snapshots`

### Occupancy Flow

`ultrasonic_sensor -> occupancy_service -> locker_service -> storage`

## Settings That Should Persist

- video resolution
- frame rate
- brightness
- sharpness
- saturation
- camera mount home angles
- occupancy thresholds

## Notes

- CSI camera support is based on `Picamera2`
- Prefer installing `python3-picamera2` with `apt` on Raspberry Pi
- RC522 depends on SPI and the `pi-rc522` stack
- If the ultrasonic sensor uses a `5V` echo pin, add voltage division before connecting to Raspberry Pi GPIO
- `config.py` is the current baseline config entry for Phase 0
- `scripts/hardware_smoke_test.py` is the shared entry point for Phase 1 device checks
