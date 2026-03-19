"""CSI camera driver based on Picamera2.

Notes:
- The main stream is intended for frontend display or high-quality snapshots.
- The low-resolution stream is intended for detection and tracking.
- The default low-resolution format is YUV420, which is efficient but may need conversion
  before passing frames into OpenCV models.
"""

import time
from pathlib import Path

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

try:
    from picamera2 import Picamera2
except ImportError:  # pragma: no cover - only hit when Picamera2 is not installed
    Picamera2 = None


class CsiCamera:
    """Simple driver for a CSI camera using Picamera2."""

    def __init__(self, camera_index: int = 0, picamera2_class=None) -> None:
        """
        Initialize the camera driver.

        Args:
            camera_index: Camera index used by Picamera2. Usually 0 for a single camera.
            picamera2_class: Optional Picamera2-compatible class for testing or mocking.
        """
        self.camera_index = camera_index
        self._picamera2_class = picamera2_class or Picamera2
        self._camera = None
        self._is_running = False
        self._current_config = None
        self._stream_size = None
        self._detection_size = None
        self._stream_format = None
        self._detection_format = None

        if self._picamera2_class is None:
            raise RuntimeError(
                "Picamera2 is not available. Install it with "
                "'sudo apt install -y python3-picamera2'."
            )

        self._camera = self._picamera2_class(camera_index)

    @property
    def is_running(self) -> bool:
        """Return whether the camera is currently streaming."""
        return self._is_running

    @property
    def stream_size(self):
        """Return the current main stream size."""
        return self._stream_size

    @property
    def detection_size(self):
        """Return the current low-resolution detection size, or None if disabled."""
        return self._detection_size

    def _validate_size(self, size, name: str) -> None:
        if size is None:
            return
        if not isinstance(size, (tuple, list)) or len(size) != 2:
            raise ValueError(f"{name} must be a (width, height) tuple")
        if size[0] <= 0 or size[1] <= 0:
            raise ValueError(f"{name} values must be > 0")

    def configure_video(
        self,
        stream_size: tuple[int, int] = (1920, 1080),
        detection_size: tuple[int, int] | None = (640, 480),
        stream_format: str = "RGB888",
        detection_format: str = "YUV420",
        buffer_count: int = 4,
        queue: bool = True,
        controls: dict | None = None,
    ) -> None:
        """
        Configure the camera for a main stream and an optional low-resolution stream.

        Args:
            stream_size: Main stream size as (width, height).
            detection_size: Low-resolution stream size as (width, height), or None to disable it.
            stream_format: Main stream pixel format, such as "RGB888".
            detection_format: Detection stream pixel format. "YUV420" is the safest default.
            buffer_count: Number of frame buffers to allocate.
            queue: If True, allow queued frames for smoother capture.
            controls: Optional camera controls to apply after configure.
        """
        self._validate_size(stream_size, "stream_size")
        self._validate_size(detection_size, "detection_size")
        if buffer_count < 1:
            raise ValueError("buffer_count must be >= 1")

        was_running = self._is_running
        if was_running:
            self.stop()

        config_kwargs = {
            "main": {"size": stream_size, "format": stream_format},
            "buffer_count": buffer_count,
            "queue": queue,
        }

        if detection_size is not None:
            config_kwargs["lores"] = {"size": detection_size, "format": detection_format}

        config = self._camera.create_video_configuration(**config_kwargs)
        self._camera.configure(config)
        self._current_config = config
        self._stream_size = stream_size
        self._detection_size = detection_size
        self._stream_format = stream_format
        self._detection_format = detection_format if detection_size is not None else None

        if controls:
            self._camera.set_controls(controls)

        if was_running:
            self.start()

    def configure_preview(
        self,
        size: tuple[int, int] = (1280, 720),
        pixel_format: str = "RGB888",
        buffer_count: int = 4,
        queue: bool = True,
        controls: dict | None = None,
    ) -> None:
        """
        Configure a simple single-stream preview mode.

        Args:
            size: Output frame size as (width, height).
            pixel_format: Main stream pixel format, such as "RGB888".
            buffer_count: Number of frame buffers to allocate.
            queue: If True, allow queued frames for smoother capture.
            controls: Optional camera controls to apply after configure.
        """
        self.configure_video(
            stream_size=size,
            detection_size=None,
            stream_format=pixel_format,
            buffer_count=buffer_count,
            queue=queue,
            controls=controls,
        )

    def start(self) -> None:
        """Start the camera stream."""
        if not self._is_running:
            if self._current_config is None:
                self.configure_video()

            self._camera.start()
            self._is_running = True

    def stop(self) -> None:
        """Stop the camera stream."""
        if self._is_running:
            self._camera.stop()
            self._is_running = False

    def warmup(self, seconds: float = 1.0) -> None:
        """
        Wait for the camera auto-controls to settle.

        Args:
            seconds: Warmup time in seconds.
        """
        if seconds < 0:
            raise ValueError("seconds must be >= 0")

        if not self._is_running:
            raise RuntimeError("Camera is not running")

        time.sleep(seconds)

    def capture_frame(self, stream: str = "main"):
        """
        Capture one frame from a configured stream as a numpy array.

        Args:
            stream: Stream name, usually "main" or "lores".
        """
        if not self._is_running:
            raise RuntimeError("Camera is not running")

        if stream == "lores" and self._detection_size is None:
            raise RuntimeError("Detection stream is not configured")

        return self._camera.capture_array(stream)

    def capture_stream_frame(self):
        """Capture one frame from the main stream."""
        return self.capture_frame("main")

    def capture_detection_frame(self):
        """Capture one raw frame from the low-resolution detection stream."""
        return self.capture_frame("lores")

    def capture_detection_frame_bgr(self):
        """
        Capture one detection frame and convert it to BGR if possible.

        This is convenient for OpenCV-based detection code.
        """
        if cv2 is None:
            raise RuntimeError("OpenCV is not available. Install python3-opencv first.")

        frame = self.capture_detection_frame()

        if self._detection_format == "YUV420":
            return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
        if self._detection_format == "RGB888":
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if self._detection_format == "BGR888":
            return frame

        raise RuntimeError(
            f"Unsupported detection format for BGR conversion: {self._detection_format}"
        )

    def capture_file(self, path: str) -> None:
        """
        Save one frame directly to a file.

        Args:
            path: Output file path, such as 'frame.jpg'.
        """
        if not self._is_running:
            raise RuntimeError("Camera is not running")

        output_path = Path(path)
        if output_path.parent != Path("."):
            output_path.parent.mkdir(parents=True, exist_ok=True)

        self._camera.capture_file(str(output_path))

    def set_controls(self, controls: dict) -> None:
        """
        Update camera controls.

        Args:
            controls: Picamera2/libcamera control values, such as frame rate or brightness.
        """
        self._camera.set_controls(controls)

    def get_camera_controls(self) -> dict:
        """Return the available camera controls and their ranges."""
        return self._camera.camera_controls

    def get_camera_properties(self) -> dict:
        """Return camera properties reported by Picamera2."""
        return self._camera.camera_properties

    def get_camera_configuration(self) -> dict:
        """Return the current camera configuration."""
        return self._camera.camera_configuration()

    def capture_metadata(self) -> dict:
        """Capture metadata for the next frame."""
        if not self._is_running:
            raise RuntimeError("Camera is not running")

        return self._camera.capture_metadata()

    def cleanup(self) -> None:
        """Stop the camera and release resources."""
        self.stop()
        if hasattr(self._camera, "close"):
            self._camera.close()

    def close(self) -> None:
        """Alias of cleanup()."""
        self.cleanup()


if __name__ == "__main__":
    camera = CsiCamera()
    try:
        camera.configure_video(
            stream_size=(1920, 1080),
            detection_size=(640, 480),
            stream_format="RGB888",
            detection_format="YUV420",
        )
        camera.start()
        camera.warmup(2)  # 预热 2 秒，让自动曝光和自动白平衡稳定一点

        main_frame = camera.capture_stream_frame()
        print("Main frame shape:", main_frame.shape)

        detection_frame = camera.capture_detection_frame()
        print("Detection frame shape:", detection_frame.shape)

        camera.capture_file("camera_test.jpg")
        print("Saved camera_test.jpg")  # 保存一张主流测试照片

        metadata = camera.capture_metadata()
        print("Metadata keys:", list(metadata.keys())[:10])  # 打印部分 metadata 键名

        if cv2 is not None:
            detection_bgr = camera.capture_detection_frame_bgr()
            print("Detection BGR shape:", detection_bgr.shape)

    finally:
        camera.cleanup()
