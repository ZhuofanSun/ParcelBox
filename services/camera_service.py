"""Camera service for Phase 2 streaming."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

from config import config
from drivers.camera import CsiCamera


class CameraService:
    """High-level camera service for streaming and snapshots."""

    SNAPSHOT_MAX_FILES = 100
    SNAPSHOT_PRUNE_COUNT = 50

    def __init__(self, camera: CsiCamera | None = None) -> None:
        self._camera = camera
        self._lock = threading.Lock()
        self._frame_condition = threading.Condition()
        self._stop_event = threading.Event()
        self._stream_thread: threading.Thread | None = None
        self._latest_stream_jpeg: bytes | None = None
        self._latest_stream_timestamp: float = 0.0
        self._started = False
        self._stream_standby_provider: Callable[[], bool] | None = None
        self._last_applied_stream_fps: int | None = None

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

            self._stop_event.clear()
            if self._camera is None:
                self._camera = CsiCamera(config.camera.camera_index)

            self._camera.configure_video(
                stream_size=config.camera.stream_size,
                detection_size=config.camera.detection_size,
                stream_format=config.camera.pixel_format,
                detection_format="YUV420",
                buffer_count=config.camera.buffer_count,
                controls=self._build_controls(),
                hflip=config.camera.hflip,
                vflip=config.camera.vflip,
            )
            self._camera.start()
            self._camera.warmup(2)
            self._started = True
            self._last_applied_stream_fps = max(config.camera.default_fps, 1)
            self._stream_thread = threading.Thread(
                target=self._stream_worker,
                name="camera-stream-worker",
                daemon=True,
            )
            self._stream_thread.start()

    def stop(self) -> None:
        """Stop the camera service."""
        self._stop_event.set()

        if self._stream_thread is not None:
            self._stream_thread.join(timeout=2)
            self._stream_thread = None

        with self._lock:
            if not self._started:
                return

            if self._camera is not None:
                self._camera.cleanup()
                self._camera = None

            with self._frame_condition:
                self._latest_stream_jpeg = None
                self._latest_stream_timestamp = 0.0
                self._frame_condition.notify_all()

            self._started = False
            self._last_applied_stream_fps = None

    def set_stream_standby_provider(self, provider: Callable[[], bool] | None) -> None:
        """Set a callback that reports whether the shared stream should run in standby mode."""
        self._stream_standby_provider = provider

    def get_stream_fps_target(self) -> int:
        """Return the current stream FPS target."""
        if self._is_stream_standby_active():
            return max(config.web.standby_stream_fps, 1)
        return max(config.web.stream_fps, 1)

    def _build_controls(self) -> dict:
        frame_duration_us = int(1_000_000 / config.camera.default_fps)
        return {
            "FrameDurationLimits": (frame_duration_us, frame_duration_us),
            "Brightness": config.camera.default_brightness,
            "ExposureValue": config.camera.default_exposure_value,
            "Sharpness": config.camera.default_sharpness,
            "Saturation": config.camera.default_saturation,
        }

    def _encode_stream_frame_jpeg(self, frame, quality: int) -> bytes:
        if cv2 is None:
            raise RuntimeError("OpenCV is required for JPEG encoding. Install python3-opencv.")

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), quality],
        )
        if not ok:
            raise RuntimeError("Failed to encode stream frame as JPEG")

        return encoded.tobytes()

    def _stream_worker(self) -> None:
        while not self._stop_event.is_set():
            started_at = time.perf_counter()

            try:
                self._sync_stream_profile()
                frame = self.get_stream_frame()
                frame_bytes = self._encode_stream_frame_jpeg(frame, config.web.jpeg_quality)

                with self._frame_condition:
                    self._latest_stream_jpeg = frame_bytes
                    self._latest_stream_timestamp = time.time()
                    self._frame_condition.notify_all()
            except Exception:
                time.sleep(0.1)
                continue

            elapsed = time.perf_counter() - started_at
            interval = 1 / max(self.get_stream_fps_target(), 1)
            remaining = max(0.0, interval - elapsed)
            self._stop_event.wait(remaining)

    def _is_stream_standby_active(self) -> bool:
        if self._stream_standby_provider is None:
            return False
        try:
            return bool(self._stream_standby_provider())
        except Exception:
            return False

    def _sync_stream_profile(self) -> None:
        target_fps = self.get_stream_fps_target()
        with self._lock:
            if self._camera is None or not self._started:
                return
            if self._last_applied_stream_fps == target_fps:
                return
            frame_duration_us = int(1_000_000 / max(target_fps, 1))
            self._camera.set_controls(
                {
                    "FrameDurationLimits": (frame_duration_us, frame_duration_us),
                }
            )
            self._last_applied_stream_fps = target_fps

    def get_stream_frame(self):
        """Get one frame from the main stream."""
        if self._camera is None:
            raise RuntimeError("Camera service is not started")
        with self._lock:
            return self._camera.capture_stream_frame()

    def get_detection_frame(self):
        """Get one frame from the low-resolution detection stream."""
        if self._camera is None:
            raise RuntimeError("Camera service is not started")
        with self._lock:
            return self._camera.capture_detection_frame()

    def get_detection_frame_bgr(self):
        """Get one BGR frame from the low-resolution detection stream."""
        if self._camera is None:
            raise RuntimeError("Camera service is not started")
        with self._lock:
            return self._camera.capture_detection_frame_bgr()

    def get_stream_frame_jpeg(self, quality: int | None = None) -> bytes:
        """
        Get one JPEG-encoded frame from the main stream.

        Args:
            quality: JPEG quality from 0 to 100. None returns the cached shared frame.
        """
        if quality is None:
            with self._frame_condition:
                if self._latest_stream_jpeg is None:
                    raise RuntimeError("No cached stream frame is available yet")
                return self._latest_stream_jpeg

        if not 0 <= quality <= 100:
            raise ValueError("quality must be between 0 and 100")

        frame = self.get_stream_frame()
        return self._encode_stream_frame_jpeg(frame, quality)

    def wait_for_latest_stream_jpeg(self, timeout: float = 2.0) -> tuple[bytes, float]:
        """
        Wait for the latest shared JPEG frame.

        Args:
            timeout: Maximum wait time in seconds.
        """
        if timeout <= 0:
            raise ValueError("timeout must be > 0")

        deadline = time.time() + timeout

        with self._frame_condition:
            while self._latest_stream_jpeg is None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise RuntimeError("Timed out waiting for stream frame")
                self._frame_condition.wait(timeout=remaining)

            return self._latest_stream_jpeg, self._latest_stream_timestamp

    def save_snapshot(self, path: str | Path) -> None:
        """Save one full-resolution snapshot to disk."""
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self._camera is None:
            raise RuntimeError("Camera service is not started")
        with self._lock:
            self._camera.capture_file(str(output_path))

    def capture_snapshot(self, directory: str | Path | None = None) -> dict:
        """Capture one snapshot to the configured snapshot directory."""
        target_dir = Path(directory) if directory is not None else Path(config.storage.snapshot_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now()
        base_name = timestamp.strftime("%Y%m%d_%H%M%S")
        output_path = target_dir / f"{base_name}.jpg"
        suffix = 1
        while output_path.exists():
            output_path = target_dir / f"{base_name}_{suffix}.jpg"
            suffix += 1

        self.save_snapshot(output_path)
        self._prune_snapshot_directory(target_dir)
        return {
            "filename": output_path.name,
            "path": str(output_path),
            "saved_at": timestamp.isoformat(),
        }

    def _prune_snapshot_directory(self, directory: Path) -> None:
        snapshot_files = sorted(path for path in directory.iterdir() if path.is_file())
        if len(snapshot_files) <= self.SNAPSHOT_MAX_FILES:
            return

        for stale_path in snapshot_files[: self.SNAPSHOT_PRUNE_COUNT]:
            try:
                stale_path.unlink()
            except FileNotFoundError:
                continue
