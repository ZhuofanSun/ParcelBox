from dataclasses import dataclass, field


@dataclass
class GPIOConfig:
    """Central place for GPIO pin assignments."""

    rc522_rst_pin: int = 22

    door_servo_pin: int | None = 18
    camera_pan_servo_pin: int | None = 13
    camera_tilt_servo_pin: int | None = 12

    button_pin: int | None = 27
    buzzer_pin: int | None = 25

    rgb_red_pin: int | None = 5
    rgb_green_pin: int | None = 6
    rgb_blue_pin: int | None = 26

    ultrasonic_trigger_pin: int | None = 16
    ultrasonic_echo_pin: int | None = 20


@dataclass
class CameraConfig:
    """Baseline camera configuration."""

    camera_index: int = 0
    stream_size: tuple[int, int] = (1280, 720)
    detection_size: tuple[int, int] = (640, 360)
    pixel_format: str = "RGB888"
    buffer_count: int = 13

    # 镜头接线放上面
    # 和镜头同朝向时：hflip == vflip == True
    # 面向镜头时：hflip = False, vflip = True
    hflip: bool = True
    vflip: bool = True

    default_fps: int = 30
    default_brightness: float = 0.0
    default_exposure_value: float = 0.5
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
    center_deadzone_ratio: float = 0.10
    pan_max_single_move_angle: float = 10
    tilt_max_single_move_angle: float = 3.5
    tracking_step: float = 0.5
    tracking_delay: float = 0.01
    tracking_cooldown_seconds: float = 0
    face_lost_home_delay_seconds: float = 0.5
    home_step: float = 1.0
    home_delay: float = 0.03
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
    same_card_cooldown_seconds: float = 3.0
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
    # Retained as a JSON fallback path; the mainline app now stores RFID cards in sqlite.
    card_store_path: str = "data/cards.json"


@dataclass
class EmailConfig:
    """Outbound email notification settings."""

    enabled: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    use_tls: bool = True
    timeout_seconds: float = 10.0
    username: str = "yingyingguai71@gmail.com"
    password: str = "tuky jcwb ncpy omnh"
    from_address: str = "yinnclja@gmail.com"
    to_addresses: list[str] = field(default_factory=lambda: ["sunz99@mcmaster.ca"])
    frontend_url: str = "http://192.168.0.106:8000/"
    request_subject: str = "ParcelBox door open request"
    request_message: str = "Someone pressed the ParcelBox request-open button."
    duplicate_request_cooldown_seconds: float = 30.0


@dataclass
class VisionConfig:
    """Face-detection runtime configuration."""

    backend: str = "opencv"
    detection_fps: int = 15
    standby_detection_fps: int = 3
    standby_after_no_face_seconds: float = 5.0
    face_model_path: str = "models/face_detection_yunet_2023mar.onnx"
    face_score_threshold: float = 0.4
    # Keep predicted face boxes alive for a very short time to reduce jitter when
    # face detection misses one or two frames.
    face_hold_frames: int = 3
    # Blend factor for the primary face box. Lower is steadier; higher is more responsive.
    face_box_smoothing: float = 0.35
    face_velocity_smoothing: float = 0.5
    face_snapshot_trigger_area_ratio: float = 0.08
    face_backend: str = "yunet"
    face_fallback_to_haar: bool = True
    yunet_score_threshold: float = 0.6
    yunet_nms_threshold: float = 0.3
    yunet_top_k: int = 20

    opencv_face_scale_factor: float = 1.1
    opencv_face_min_neighbors: int = 5
    opencv_face_min_size: int = 40


@dataclass
class WebConfig:
    """Web runtime configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    stream_fps: int = 30
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
    email: EmailConfig = field(default_factory=EmailConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    web: WebConfig = field(default_factory=WebConfig)


config = AppConfig()
