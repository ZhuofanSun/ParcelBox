import time

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

    def configure_preview(
        self,
        size: tuple[int, int] = (1280, 720),
        pixel_format: str = "RGB888",
        buffer_count: int = 4,
        queue: bool = True,
        controls: dict | None = None,
    ) -> None:
        """
        Configure the camera for preview-style streaming.

        Args:
            size: Output frame size as (width, height).
            pixel_format: Main stream pixel format, such as "RGB888" or "BGR888".
            buffer_count: Number of frame buffers to allocate.
            queue: If True, allow queued frames for smoother capture.
            controls: Optional camera controls to apply after configure.
        """
        was_running = self._is_running
        if was_running:
            self.stop()

        config = self._camera.create_preview_configuration(
            main={"size": size, "format": pixel_format},
            buffer_count=buffer_count,
            queue=queue,
        )
        self._camera.configure(config)
        self._current_config = config

        if controls:
            self._camera.set_controls(controls)

        if was_running:
            self.start()

    def start(self) -> None:
        """Start the camera stream."""
        if not self._is_running:
            if self._current_config is None:
                self.configure_preview()

            self._camera.start()
            self._is_running = True

    def stop(self) -> None:
        """Stop the camera stream."""
        if self._is_running:
            self._camera.stop()
            self._is_running = False

    def capture_frame(self):
        """Capture one frame from the main stream as a numpy array."""
        if not self._is_running:
            raise RuntimeError("Camera is not running")

        return self._camera.capture_array("main")

    def capture_file(self, path: str) -> None:
        """
        Save one frame directly to a file.

        Args:
            path: Output file path, such as 'frame.jpg'.
        """
        if not self._is_running:
            raise RuntimeError("Camera is not running")

        self._camera.capture_file(path)

    def set_controls(self, controls: dict) -> None:
        """
        Update camera controls.

        Args:
            controls: Picamera2/libcamera control values, such as exposure or gain.
        """
        self._camera.set_controls(controls)

    def get_camera_controls(self) -> dict:
        """Return the available camera controls and their ranges."""
        return self._camera.camera_controls

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
        camera.configure_preview(size=(1920, 1080), pixel_format="RGB888")
        camera.start()
        time.sleep(2)  # 预热 2 秒，让自动曝光和自动白平衡稳定一点

        frame = camera.capture_frame()
        print("Frame shape:", frame.shape)

        camera.capture_file("camera_test1.jpg")
        print("Saved camera_test.jpg")  # 保存一张测试照片

        metadata = camera.capture_metadata()
        print("Metadata keys:", list(metadata.keys())[:10])  # 打印部分 metadata 键名


    finally:
        camera.cleanup()
