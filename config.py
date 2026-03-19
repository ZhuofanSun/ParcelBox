from dataclasses import dataclass, field


@dataclass
class GPIOConfig:
    """Central place for GPIO pin assignments."""

    rc522_rst_pin: int = 25

    door_servo_pin: int | None = 18
    camera_pan_servo_pin: int | None = 24
    camera_tilt_servo_pin: int | None = 23

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
    preview_size: tuple[int, int] = (1920, 1080)
    pixel_format: str = "RGB888"
    buffer_count: int = 4

    default_fps: int = 30
    default_brightness: float = 0.0
    default_sharpness: float = 1.0
    default_saturation: float = 1.0


@dataclass
class CameraMountConfig:
    """Standby and movement settings for pan / tilt servos."""

    pan_home_angle: float = 90
    tilt_home_angle: float = 90

    pan_min_angle: float = 0
    pan_max_angle: float = 160
    tilt_min_angle: float = 0
    tilt_max_angle: float = 160

    tracking_step: float = 2
    tracking_delay: float = 0.02


@dataclass
class UltrasonicConfig:
    """Baseline thresholds for locker occupancy detection."""

    occupied_threshold_cm: float = 40.0
    empty_threshold_cm: float = 100.0
    sample_count: int = 5
    sample_interval: float = 0.05


@dataclass
class StorageConfig:
    """Storage-related configuration."""

    database_url: str = "sqlite:///iot_locker.db"
    snapshot_dir: str = "data/snapshots"


@dataclass
class AppConfig:
    """Top-level application configuration."""

    gpio: GPIOConfig = field(default_factory=GPIOConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    camera_mount: CameraMountConfig = field(default_factory=CameraMountConfig)
    ultrasonic: UltrasonicConfig = field(default_factory=UltrasonicConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)


config = AppConfig()
