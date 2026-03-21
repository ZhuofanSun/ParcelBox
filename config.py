from dataclasses import dataclass, field


@dataclass
class GPIOConfig:
    """Central place for GPIO pin assignments."""

    rc522_rst_pin: int = 25

    door_servo_pin: int | None = 18
    camera_pan_servo_pin: int | None = 23
    camera_tilt_servo_pin: int | None = 24

    button_pin: int | None = 27
    buzzer_pin: int | None = 12

    rgb_red_pin: int | None = 13
    rgb_green_pin: int | None = 19
    rgb_blue_pin: int | None = 26

    ultrasonic_trigger_pin: int | None = 16
    ultrasonic_echo_pin: int | None = 20


@dataclass
class CameraConfig:
    """Baseline camera configuration."""

    camera_index: int = 0
    stream_size: tuple[int, int] = (1280, 720)
    detection_size: tuple[int, int] = (480, 480)
    pixel_format: str = "RGB888"
    buffer_count: int = 8

    # 镜头接线放上面
    # 和镜头同朝向时：hflip == vflip == True
    # 面向镜头时：hflip = False, vflip = True
    hflip: bool = True
    vflip: bool = True

    default_fps: int = 30
    default_brightness: float = 0.0
    default_exposure_value: float = -0.5
    default_sharpness: float = 1.0
    default_saturation: float = 1.0


@dataclass
class CameraMountConfig:
    """Standby and movement settings for pan / tilt servos."""

    enabled: bool = True
    pan_home_angle: float = 90
    tilt_home_angle: float = 80

    pan_min_angle: float = 20
    pan_max_angle: float = 160
    tilt_min_angle: float = 60
    tilt_max_angle: float = 120

    invert_pan_direction: bool = False
    invert_tilt_direction: bool = False
    center_deadzone_ratio: float = 0.15
    pan_max_single_move_angle: float = 3.0
    tilt_max_single_move_angle: float = 3.0
    tracking_step: float = 1.0
    tracking_delay: float = 0.05
    tracking_cooldown_seconds: float = 0.3
    no_face_home_interval_seconds: float = 3.0


@dataclass
class DoorConfig:
    """Servo movement settings for the locker door."""

    enabled: bool = True
    closed_angle: float = 0.0
    open_angle: float = 90.0
    auto_close_seconds: float = 10.0
    min_angle: float = 0.0
    max_angle: float = 180.0
    move_step: float = 5.0
    move_delay: float = 0.02


@dataclass
class RFIDConfig:
    """RFID reader polling and debounce settings."""

    enabled: bool = True
    spi_bus: int = 0
    spi_device: int = 0
    irq_pin: int | None = None
    scan_timeout_seconds: float = 0.25
    poll_interval_seconds: float = 0.08
    same_card_cooldown_seconds: float = 1.5
    enroll_scan_timeout_seconds: float = 10.0
    text_start_block: int = 4
    text_block_count: int = 4


@dataclass
class UltrasonicConfig:
    """Baseline thresholds for locker occupancy detection."""

    # <= occupied_threshold_cm: occupied
    # > occupied_threshold_cm: use door_state to distinguish empty vs door_not_closed
    occupied_threshold_cm: float = 20.0
    # Retained for compatibility; current occupancy logic does not use this value.
    empty_threshold_cm: float = 50.0
    sample_count: int = 5
    sample_interval: float = 0.1


@dataclass
class StorageConfig:
    """Storage-related configuration."""

    database_url: str = "sqlite:///iot_locker.db"
    snapshot_dir: str = "data/snapshots"
    card_store_path: str = "data/cards.json"


@dataclass
class VisionConfig:
    """Vision runtime configuration."""

    backend: str = "opencv"
    # person: only run person detection
    # face: only run face detection
    # auto: use a small state machine:
    # person_search -> face_track -> face_hold -> person_search
    # The service searches with person detection, switches to face detection when
    # the largest person box is close enough, and allows short predicted hold frames
    # before returning to person detection.
    mode: str = "auto"
    detection_fps: int = 5

    # Select which person detector to use under the OpenCV backend.
    # Supported values currently include: hog, mp_persondet, nanodet.
    person_backend: str = "nanodet"
    person_fallback_to_hog: bool = True
    # person_model_path should match the selected person_backend.
    # Current mainline baseline uses NanoDet.
    person_model_path: str = "models/object_detection_nanodet_2022nov.onnx"
    face_model_path: str = "models/face_detection_yunet_2023mar.onnx"

    person_score_threshold: float = 0.4
    face_score_threshold: float = 0.4
    person_max_results: int = 3
    face_near_trigger_ratio: float = 0.28
    # auto mode uses lower fps while searching for a person and higher fps after
    # locking onto a face.
    auto_person_detection_fps: int = 3
    auto_face_detection_fps: int = 8
    # Keep predicted face boxes alive for a very short time to reduce jitter when
    # face detection misses one or two frames.
    auto_face_hold_frames: int = 2
    auto_face_velocity_smoothing: float = 0.5
    mp_persondet_score_threshold: float = 0.5
    mp_persondet_nms_threshold: float = 0.3
    mp_persondet_top_k: int = 3

    # NanoDet-specific tuning.
    nanodet_prob_threshold: float = 0.35
    nanodet_iou_threshold: float = 0.3
    nanodet_input_size: tuple[int, int] = (416, 416)
    face_backend: str = "yunet"
    face_fallback_to_haar: bool = True
    yunet_score_threshold: float = 0.7
    yunet_nms_threshold: float = 0.3
    yunet_top_k: int = 20

    opencv_person_stride: int = 8
    opencv_person_padding: int = 8
    opencv_person_scale: float = 1.05
    opencv_face_scale_factor: float = 1.1
    opencv_face_min_neighbors: int = 5
    opencv_face_min_size: int = 40


@dataclass
class WebConfig:
    """Web runtime configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    stream_fps: int = 15
    jpeg_quality: int = 70
    access_log: bool = False


@dataclass
class AppConfig:
    """Top-level application configuration."""

    gpio: GPIOConfig = field(default_factory=GPIOConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    camera_mount: CameraMountConfig = field(default_factory=CameraMountConfig)
    door: DoorConfig = field(default_factory=DoorConfig)
    rfid: RFIDConfig = field(default_factory=RFIDConfig)
    ultrasonic: UltrasonicConfig = field(default_factory=UltrasonicConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    web: WebConfig = field(default_factory=WebConfig)


config = AppConfig()
