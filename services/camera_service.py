"""Camera service for Phase 2 streaming."""

from __future__ import annotations

import threading
from pathlib import Path

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

from config import config
from drivers.camera import CsiCamera


class CameraService:
    """High-level camera service for streaming and snapshots."""

    def __init__(self, camera: CsiCamera | None = None) -> None:
        self._camera = camera or CsiCamera(config.camera.camera_index)
        self._lock = threading.Lock()
        self._started = False

    @property
    def stream_size(self) -> tuple[int, int]:
        """Return the configured main stream size."""
        return config.camera.stream_size

    @property
    def detection_size(self) -> tuple[int, int]:
        """Return the configured detection stream size."""
        return config.camera.detection_size

    def start(self) -> None:
        """Configure and start the camera if it is not already running."""
        with self._lock:
            if self._started:
                return

            self._camera.configure_video(
                stream_size=config.camera.stream_size,
                detection_size=config.camera.detection_size,
                stream_format=config.camera.pixel_format,
                detection_format="YUV420",
                buffer_count=config.camera.buffer_count,
                controls=self._build_controls(),
            )
            self._camera.start()
            self._camera.warmup(2)
            self._started = True

    def stop(self) -> None:
        """Stop the camera service."""
        with self._lock:
            if not self._started:
                return

            self._camera.cleanup()
            self._started = False

    def _build_controls(self) -> dict:
        frame_duration_us = int(1_000_000 / config.camera.default_fps)
        return {
            "FrameDurationLimits": (frame_duration_us, frame_duration_us),
            "Brightness": config.camera.default_brightness,
            "Sharpness": config.camera.default_sharpness,
            "Saturation": config.camera.default_saturation,
        }

    def get_stream_frame(self):
        """Get one frame from the main stream."""
        with self._lock:
            return self._camera.capture_stream_frame()

    def get_detection_frame(self):
        """Get one frame from the low-resolution detection stream."""
        with self._lock:
            return self._camera.capture_detection_frame()

    def get_stream_frame_jpeg(self, quality: int = 85) -> bytes:
        """
        Get one JPEG-encoded frame from the main stream.

        Args:
            quality: JPEG quality from 0 to 100.
        """
        if cv2 is None:
            raise RuntimeError("OpenCV is required for JPEG encoding. Install python3-opencv.")

        if not 0 <= quality <= 100:
            raise ValueError("quality must be between 0 and 100")

        frame = self.get_stream_frame()
        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(
            ".jpg",
            bgr_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), quality],
        )
        if not ok:
            raise RuntimeError("Failed to encode stream frame as JPEG")

        return encoded.tobytes()

    def save_snapshot(self, path: str | Path) -> None:
        """Save one full-resolution snapshot to disk."""
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._camera.capture_file(str(output_path))
