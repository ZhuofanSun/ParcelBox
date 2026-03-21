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
    stream_size: tuple[int, int] = (1280, 720)
    detection_size: tuple[int, int] = (640, 480)
    pixel_format: str = "RGB888"
    buffer_count: int = 8

    # 镜头接线放上面
    # 和镜头同朝向时：hflip == vflip == True
    # 面向镜头时：hflip = False, vflip = True
    hflip: bool = False
    vflip: bool = True

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
class VisionConfig:
    """Vision runtime configuration."""

    backend: str = "opencv"
    # person: only run person detection
    # face: only run face detection
    # auto: run person detection first, and only switch to face detection when
    # the largest person box is close enough based on face_near_trigger_ratio
    mode: str = "person"
    detection_fps: int = 5

    # Select which person detector to use under the OpenCV backend.
    # Supported values currently include: hog, mp_persondet, nanodet.
    person_backend: str = "nanodet"
    person_fallback_to_hog: bool = True
    # person_model_path should match the selected person_backend.
    # Current branch baseline uses NanoDet.
    person_model_path: str = "models/object_detection_nanodet_2022nov.onnx"
    face_model_path: str = "models/face_detection_yunet_2023mar.onnx"
    yolo_model_path: str = "models/yolo26n.pt"

    person_score_threshold: float = 0.35
    face_score_threshold: float = 0.5
    person_max_results: int = 3
    face_near_trigger_ratio: float = 0.28
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
    stream_fps: int = 30
    jpeg_quality: int = 70
    access_log: bool = False


@dataclass
class AppConfig:
    """Top-level application configuration."""

    gpio: GPIOConfig = field(default_factory=GPIOConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    camera_mount: CameraMountConfig = field(default_factory=CameraMountConfig)
    ultrasonic: UltrasonicConfig = field(default_factory=UltrasonicConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    web: WebConfig = field(default_factory=WebConfig)


config = AppConfig()
