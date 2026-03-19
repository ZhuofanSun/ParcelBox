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

## Current Frontend Direction

- Show a continuous live video stream
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

### `services/vision_service.py`

Vision understanding only.

- person detection
- face detection
- tracking target state
- clear-frame scoring
- output boxes and tracking data

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
