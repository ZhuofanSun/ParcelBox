"""Phase 2 vision service with a pluggable backend."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from config import config
from services.vision_backends import build_vision_backend

if TYPE_CHECKING:
    from services.camera_service import CameraService


class VisionService:
    """Background vision service for person / face detection."""

    def __init__(self, camera_service: CameraService) -> None:
        self._camera_service = camera_service
        self._frame_condition = threading.Condition()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._latest_payload: dict | None = None
        self._latest_version = 0
        self._started = False
        self._backend = None
        self._auto_state = "person_search"
        self._tracked_face_box: dict | None = None
        self._tracked_face_velocity = (0.0, 0.0)
        self._face_miss_count = 0
        self._face_snapshot_taken = False

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
        """Stop the background detection loop and release detectors."""
        self._stop_event.set()

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None

        self._close_backend()

        with self._frame_condition:
            self._started = False
            self._latest_payload = None
            self._latest_version = 0
            self._frame_condition.notify_all()

        self._reset_auto_tracking()
        self._face_snapshot_taken = False

    def get_boxes(self) -> dict:
        """Return the latest detection payload."""
        with self._frame_condition:
            if self._latest_payload is None:
                return self._build_empty_payload(
                    configured_mode=self._normalized_mode(),
                    active_mode="warming_up",
                    status="warming_up",
                    error=None,
                    latency_ms=0.0,
                )
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
        while not self._stop_event.is_set():
            interval = self._current_detection_interval()
            started_at = time.perf_counter()
            payload = self._run_detection_cycle()

            with self._frame_condition:
                self._latest_payload = payload
                self._latest_version += 1
                self._frame_condition.notify_all()

            elapsed = time.perf_counter() - started_at
            remaining = max(0.0, interval - elapsed)
            self._stop_event.wait(remaining)

    def _current_detection_interval(self) -> float:
        fps = self._current_detection_fps_target()
        return 1 / max(fps, 1)

    def _current_detection_fps_target(self) -> int:
        configured_mode = self._normalized_mode()
        if configured_mode != "auto":
            return config.vision.detection_fps

        if self._auto_state in {"face_track", "face_hold"}:
            return config.vision.auto_face_detection_fps
        return config.vision.auto_person_detection_fps

    def _run_detection_cycle(self) -> dict:
        configured_mode = self._normalized_mode()
        started_at = time.perf_counter()

        try:
            frame_bgr = self._camera_service.get_detection_frame_bgr()
        except Exception as error:
            return self._build_empty_payload(
                configured_mode=configured_mode,
                active_mode="camera_error",
                status="camera_error",
                error=str(error),
                latency_ms=0.0,
            )

        try:
            backend = self._ensure_backend()

            if configured_mode == "person":
                self._reset_auto_tracking()
                boxes = backend.detect_person(frame_bgr)
                active_mode = "person"
            elif configured_mode == "face":
                self._reset_auto_tracking()
                boxes = backend.detect_face(frame_bgr)
                active_mode = "face"
            else:
                boxes, active_mode = self._detect_auto_boxes(backend, frame_bgr)

            mapped_boxes = self._map_detection_boxes_to_stream(boxes)
            self._maybe_capture_face_snapshot(mapped_boxes)
            latency_ms = (time.perf_counter() - started_at) * 1000

            return self._build_payload(
                configured_mode=configured_mode,
                active_mode=active_mode,
                boxes=mapped_boxes,
                status="ok",
                error=None,
                latency_ms=latency_ms,
            )
        except Exception as error:
            return self._build_empty_payload(
                configured_mode=configured_mode,
                active_mode="detector_error",
                status="detector_error",
                error=str(error),
                latency_ms=(time.perf_counter() - started_at) * 1000,
            )

    def _ensure_backend(self):
        if self._backend is None:
            self._backend = build_vision_backend()
        return self._backend

    def _normalized_mode(self) -> str:
        mode = config.vision.mode.lower().strip()
        if mode not in {"person", "face", "auto"}:
            return "person"
        return mode

    def _detect_auto_boxes(self, backend, frame_bgr) -> tuple[list[dict], str]:
        if self._auto_state == "person_search":
            person_boxes = backend.detect_person(frame_bgr)
            if self._is_person_near(person_boxes):
                self._auto_state = "face_track"
                self._face_miss_count = 0
            else:
                self._clear_face_track()
            return person_boxes, "person"

        face_boxes = backend.detect_face(frame_bgr)
        if face_boxes:
            self._update_face_track(face_boxes)
            self._auto_state = "face_track"
            self._face_miss_count = 0
            return face_boxes, "face"

        self._face_miss_count += 1
        predicted_boxes = self._predict_face_boxes()
        if predicted_boxes and self._face_miss_count <= config.vision.auto_face_hold_frames:
            self._auto_state = "face_hold"
            return predicted_boxes, "face"

        self._clear_face_track()
        self._auto_state = "person_search"
        person_boxes = backend.detect_person(frame_bgr)
        if self._is_person_near(person_boxes):
            self._auto_state = "face_track"
            self._face_miss_count = 0
        return person_boxes, "person"

    def _update_face_track(self, face_boxes: list[dict]) -> None:
        if not face_boxes:
            return

        primary_box = dict(face_boxes[0])
        if self._tracked_face_box is None:
            self._tracked_face_box = primary_box
            self._tracked_face_velocity = (0.0, 0.0)
            return

        previous_center = self._box_center(self._tracked_face_box)
        current_center = self._box_center(primary_box)
        raw_velocity = (
            current_center[0] - previous_center[0],
            current_center[1] - previous_center[1],
        )
        smoothing = config.vision.auto_face_velocity_smoothing
        self._tracked_face_velocity = (
            self._tracked_face_velocity[0] * (1.0 - smoothing) + raw_velocity[0] * smoothing,
            self._tracked_face_velocity[1] * (1.0 - smoothing) + raw_velocity[1] * smoothing,
        )
        self._tracked_face_box = primary_box

    def _predict_face_boxes(self) -> list[dict]:
        if self._tracked_face_box is None:
            return []

        shift_x = self._tracked_face_velocity[0]
        shift_y = self._tracked_face_velocity[1]
        predicted_box = dict(self._tracked_face_box)
        predicted_box["x1"] = int(round(predicted_box["x1"] + shift_x))
        predicted_box["y1"] = int(round(predicted_box["y1"] + shift_y))
        predicted_box["x2"] = int(round(predicted_box["x2"] + shift_x))
        predicted_box["y2"] = int(round(predicted_box["y2"] + shift_y))
        predicted_box["score"] = round(float(predicted_box["score"]) * 0.98, 3)

        detection_width, detection_height = config.camera.detection_size
        predicted_box["x1"] = max(0, min(detection_width - 1, predicted_box["x1"]))
        predicted_box["y1"] = max(0, min(detection_height - 1, predicted_box["y1"]))
        predicted_box["x2"] = max(predicted_box["x1"] + 1, min(detection_width, predicted_box["x2"]))
        predicted_box["y2"] = max(predicted_box["y1"] + 1, min(detection_height, predicted_box["y2"]))

        self._tracked_face_box = predicted_box
        return [predicted_box]

    def _clear_face_track(self) -> None:
        self._tracked_face_box = None
        self._tracked_face_velocity = (0.0, 0.0)
        self._face_miss_count = 0

    def _reset_auto_tracking(self) -> None:
        self._auto_state = "person_search"
        self._clear_face_track()

    def _box_center(self, box: dict) -> tuple[float, float]:
        center_x = (box["x1"] + box["x2"]) / 2
        center_y = (box["y1"] + box["y2"]) / 2
        return center_x, center_y

    def _is_person_near(self, detection_boxes: list[dict]) -> bool:
        if not detection_boxes:
            return False

        detection_height = config.camera.detection_size[1]
        largest_box = detection_boxes[0]
        height_ratio = (largest_box["y2"] - largest_box["y1"]) / max(detection_height, 1)
        return height_ratio >= config.vision.face_near_trigger_ratio

    def _map_detection_boxes_to_stream(self, detection_boxes: list[dict]) -> list[dict]:
        detection_width, detection_height = config.camera.detection_size
        stream_width, stream_height = config.camera.stream_size

        stream_boxes = []
        for box in detection_boxes:
            x1 = int(round(box["x1"] * stream_width / detection_width))
            y1 = int(round(box["y1"] * stream_height / detection_height))
            x2 = int(round(box["x2"] * stream_width / detection_width))
            y2 = int(round(box["y2"] * stream_height / detection_height))

            x1 = max(0, min(stream_width - 1, x1))
            y1 = max(0, min(stream_height - 1, y1))
            x2 = max(x1 + 1, min(stream_width, x2))
            y2 = max(y1 + 1, min(stream_height, y2))

            stream_boxes.append(
                {
                    "id": box["id"],
                    "label": box["label"],
                    "score": box["score"],
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )

        stream_boxes.sort(
            key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]),
            reverse=True,
        )
        return stream_boxes

    def _build_payload(
        self,
        configured_mode: str,
        active_mode: str,
        boxes: list[dict],
        status: str,
        error: str | None,
        latency_ms: float,
    ) -> dict:
        stream_width, stream_height = config.camera.stream_size
        detection_width, detection_height = config.camera.detection_size
        runtime_info = self._get_backend_runtime_info()
        if configured_mode == "auto":
            runtime_info["auto_state"] = self._auto_state
            runtime_info["current_detection_fps_target"] = self._current_detection_fps_target()

        return {
            "mode": configured_mode,
            "active_mode": active_mode,
            "status": status,
            "backend": config.vision.backend,
            "runtime": runtime_info,
            "frame_size": {
                "width": stream_width,
                "height": stream_height,
            },
            "detection_size": {
                "width": detection_width,
                "height": detection_height,
            },
            "boxes": boxes,
            "target": self._build_target(boxes),
            "timestamp": time.time(),
            "latency_ms": round(latency_ms, 2),
            "error": error,
        }

    def _get_backend_runtime_info(self) -> dict:
        if self._backend is None:
            return {}

        getter = getattr(self._backend, "get_runtime_info", None)
        if getter is None:
            return {}

        try:
            runtime_info = getter()
        except Exception:
            return {}

        return runtime_info if isinstance(runtime_info, dict) else {}

    def _build_empty_payload(
        self,
        configured_mode: str,
        active_mode: str,
        status: str,
        error: str | None,
        latency_ms: float,
    ) -> dict:
        return self._build_payload(
            configured_mode=configured_mode,
            active_mode=active_mode,
            boxes=[],
            status=status,
            error=error,
            latency_ms=latency_ms,
        )

    def _build_target(self, boxes: list[dict]) -> dict | None:
        if not boxes:
            return None

        largest_box = boxes[0]
        center_x = (largest_box["x1"] + largest_box["x2"]) / 2
        center_y = (largest_box["y1"] + largest_box["y2"]) / 2

        return {
            "id": largest_box["id"],
            "label": largest_box["label"],
            "center_x": round(center_x, 1),
            "center_y": round(center_y, 1),
        }

    def _maybe_capture_face_snapshot(self, boxes: list[dict]) -> None:
        face_box = self._largest_face_box(boxes)
        if face_box is None:
            self._face_snapshot_taken = False
            return

        if self._face_snapshot_taken:
            return

        area_ratio = self._box_area_ratio(face_box)
        if area_ratio < config.vision.face_snapshot_trigger_area_ratio:
            return

        try:
            self._camera_service.capture_snapshot()
        except Exception:
            return

        self._face_snapshot_taken = True

    def _largest_face_box(self, boxes: list[dict]) -> dict | None:
        face_boxes = [box for box in boxes if box.get("label") == "face"]
        if not face_boxes:
            return None

        return max(
            face_boxes,
            key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]),
        )

    def _box_area_ratio(self, box: dict) -> float:
        stream_width, stream_height = config.camera.stream_size
        frame_area = max(stream_width * stream_height, 1)
        box_area = max(box["x2"] - box["x1"], 0) * max(box["y2"] - box["y1"], 0)
        return box_area / frame_area

    def _close_backend(self) -> None:
        if self._backend is not None and hasattr(self._backend, "close"):
            self._backend.close()
        self._backend = None
