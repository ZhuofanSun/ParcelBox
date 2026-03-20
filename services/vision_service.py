"""Temporary Phase 2 fake vision service."""

from __future__ import annotations

import math
import threading
import time

from config import config


class VisionService:
    """Fake vision output used to validate frontend overlays."""

    def __init__(self) -> None:
        self._frame_condition = threading.Condition()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._latest_payload: dict | None = None
        self._latest_version = 0
        self._started = False

    def start(self) -> None:
        """Start the background detection loop."""
        with self._frame_condition:
            if self._started:
                return

            self._stop_event.clear()
            self._started = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="vision-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def stop(self) -> None:
        """Stop the background detection loop."""
        self._stop_event.set()

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None

        with self._frame_condition:
            self._started = False
            self._latest_payload = None
            self._latest_version = 0
            self._frame_condition.notify_all()

    def get_boxes(self) -> dict:
        """Return the latest detection payload."""
        with self._frame_condition:
            if self._latest_payload is None:
                return self._build_fake_payload()
            return self._latest_payload

    def wait_for_latest_boxes(
        self,
        last_seen_version: int = 0,
        timeout: float = 2.0,
    ) -> tuple[dict, int]:
        """
        Wait until a newer detection payload is available.

        Args:
            last_seen_version: The last payload version already sent to the client.
            timeout: Maximum wait time in seconds.
        """
        if timeout <= 0:
            raise ValueError("timeout must be > 0")

        deadline = time.time() + timeout

        with self._frame_condition:
            while self._latest_version <= last_seen_version:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for latest boxes")
                self._frame_condition.wait(timeout=remaining)

            return self._latest_payload, self._latest_version

    def _worker_loop(self) -> None:
        interval = 1 / max(config.vision.detection_fps, 1)

        while not self._stop_event.is_set():
            started_at = time.perf_counter()
            payload = self._build_fake_payload()

            with self._frame_condition:
                self._latest_payload = payload
                self._latest_version += 1
                self._frame_condition.notify_all()

            elapsed = time.perf_counter() - started_at
            remaining = max(0.0, interval - elapsed)
            self._stop_event.wait(remaining)

    def _build_fake_payload(self) -> dict:
        now = time.time()
        stream_width, stream_height = config.camera.stream_size

        box_width = int(stream_width * 0.18)
        box_height = int(stream_height * 0.38)
        center_x = int(stream_width * 0.5 + math.sin(now * 0.8) * stream_width * 0.22)
        center_y = int(stream_height * 0.5 + math.cos(now * 0.6) * stream_height * 0.12)

        x1 = max(0, center_x - box_width // 2)
        y1 = max(0, center_y - box_height // 2)
        x2 = min(stream_width - 1, x1 + box_width)
        y2 = min(stream_height - 1, y1 + box_height)

        return {
            "mode": "fake_person",
            "frame_size": {
                "width": stream_width,
                "height": stream_height,
            },
            "boxes": [
                {
                    "id": "fake-person-1",
                    "label": "person",
                    "score": 0.99,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            ],
            "timestamp": now,
        }
