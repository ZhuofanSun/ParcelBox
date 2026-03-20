"""Phase 2 vision service backed by MediaPipe Tasks."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

try:
    import mediapipe as mp
except ImportError:  # pragma: no cover - optional dependency
    mp = None

from config import config

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
        self._person_detector = None
        self._face_detector = None

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

        self._close_detectors()

        with self._frame_condition:
            self._started = False
            self._latest_payload = None
            self._latest_version = 0
            self._frame_condition.notify_all()

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
        interval = 1 / max(config.vision.detection_fps, 1)

        while not self._stop_event.is_set():
            started_at = time.perf_counter()
            payload = self._run_detection_cycle()

            with self._frame_condition:
                self._latest_payload = payload
                self._latest_version += 1
                self._frame_condition.notify_all()

            elapsed = time.perf_counter() - started_at
            remaining = max(0.0, interval - elapsed)
            self._stop_event.wait(remaining)

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
            self._ensure_detectors(configured_mode)
            mp_image = self._build_mp_image(frame_bgr)
            timestamp_ms = int(time.monotonic_ns() / 1_000_000)

            if configured_mode == "person":
                boxes = self._detect_person_boxes(mp_image, timestamp_ms)
                active_mode = "person"
            elif configured_mode == "face":
                boxes = self._detect_face_boxes(mp_image, timestamp_ms)
                active_mode = "face"
            else:
                boxes, active_mode = self._detect_auto_boxes(mp_image, timestamp_ms)

            latency_ms = (time.perf_counter() - started_at) * 1000
            return self._build_payload(
                configured_mode=configured_mode,
                active_mode=active_mode,
                boxes=boxes,
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

    def _normalized_mode(self) -> str:
        mode = config.vision.mode.lower().strip()
        if mode not in {"person", "face", "auto"}:
            return "person"
        return mode

    def _ensure_detectors(self, configured_mode: str) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is not available. Install python3-opencv first.")
        if mp is None:
            raise RuntimeError("MediaPipe is not available. Run 'pip install -r requirements.txt'.")

        if configured_mode in {"person", "auto"} and self._person_detector is None:
            self._person_detector = self._create_person_detector()

        if configured_mode in {"face", "auto"} and self._face_detector is None:
            self._face_detector = self._create_face_detector()

    def _create_person_detector(self):
        model_path = self._resolve_model_path(config.vision.person_model_path)
        if not model_path.is_file():
            raise RuntimeError(f"Person detector model not found: {model_path}")

        base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
        options = mp.tasks.vision.ObjectDetectorOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            max_results=config.vision.person_max_results,
            score_threshold=config.vision.person_score_threshold,
            category_allowlist=["person"],
        )
        return mp.tasks.vision.ObjectDetector.create_from_options(options)

    def _create_face_detector(self):
        model_path = self._resolve_model_path(config.vision.face_model_path)
        if not model_path.is_file():
            raise RuntimeError(f"Face detector model not found: {model_path}")

        base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
        options = mp.tasks.vision.FaceDetectorOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            min_detection_confidence=config.vision.face_score_threshold,
        )
        return mp.tasks.vision.FaceDetector.create_from_options(options)

    def _resolve_model_path(self, path: str) -> Path:
        model_path = Path(path)
        if not model_path.is_absolute():
            model_path = Path(__file__).resolve().parent.parent / model_path
        return model_path

    def _build_mp_image(self, frame_bgr):
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

    def _detect_person_boxes(self, mp_image, timestamp_ms: int) -> list[dict]:
        result = self._person_detector.detect_for_video(mp_image, timestamp_ms)
        return self._convert_detections_to_boxes(
            result.detections,
            default_label="person",
        )

    def _detect_face_boxes(self, mp_image, timestamp_ms: int) -> list[dict]:
        result = self._face_detector.detect_for_video(mp_image, timestamp_ms)
        return self._convert_detections_to_boxes(
            result.detections,
            default_label="face",
        )

    def _detect_auto_boxes(self, mp_image, timestamp_ms: int) -> tuple[list[dict], str]:
        person_boxes = self._detect_person_boxes(mp_image, timestamp_ms)
        if not self._is_person_near(person_boxes):
            return person_boxes, "person"

        face_boxes = self._detect_face_boxes(mp_image, timestamp_ms)
        if face_boxes:
            return face_boxes, "face"

        return person_boxes, "person"

    def _convert_detections_to_boxes(self, detections, default_label: str) -> list[dict]:
        detection_width, detection_height = config.camera.detection_size
        stream_width, stream_height = config.camera.stream_size

        boxes = []
        for index, detection in enumerate(detections):
            bounding_box = detection.bounding_box
            categories = list(getattr(detection, "categories", []))
            best_category = categories[0] if categories else None
            label = default_label
            score = 0.0

            if best_category is not None:
                score = float(getattr(best_category, "score", 0.0))
                category_name = getattr(best_category, "category_name", None)
                if category_name:
                    label = category_name

            x1 = int(round(bounding_box.origin_x * stream_width / detection_width))
            y1 = int(round(bounding_box.origin_y * stream_height / detection_height))
            x2 = int(round((bounding_box.origin_x + bounding_box.width) * stream_width / detection_width))
            y2 = int(round((bounding_box.origin_y + bounding_box.height) * stream_height / detection_height))

            x1 = max(0, min(stream_width - 1, x1))
            y1 = max(0, min(stream_height - 1, y1))
            x2 = max(x1 + 1, min(stream_width, x2))
            y2 = max(y1 + 1, min(stream_height, y2))

            boxes.append(
                {
                    "id": f"{default_label}-{index + 1}",
                    "label": label,
                    "score": score,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )

        boxes.sort(key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]), reverse=True)
        return boxes

    def _is_person_near(self, boxes: list[dict]) -> bool:
        if not boxes:
            return False

        stream_height = config.camera.stream_size[1]
        largest_box = boxes[0]
        height_ratio = (largest_box["y2"] - largest_box["y1"]) / max(stream_height, 1)
        return height_ratio >= config.vision.face_near_trigger_ratio

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

        return {
            "mode": configured_mode,
            "active_mode": active_mode,
            "status": status,
            "backend": "mediapipe",
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

    def _close_detectors(self) -> None:
        for detector_name in ("_person_detector", "_face_detector"):
            detector = getattr(self, detector_name)
            if detector is not None and hasattr(detector, "close"):
                detector.close()
            setattr(self, detector_name, None)
