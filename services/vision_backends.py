"""Backend implementations for vision detection."""

from __future__ import annotations

import math
from pathlib import Path

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

from config import config


class OpenCvVisionBackend:
    """OpenCV-based baseline backend for person and face detection."""

    name = "opencv"

    def __init__(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is not available. Install python3-opencv first.")

        self._hog = None
        self._face_cascade = None

    def detect_person(self, frame_bgr) -> list[dict]:
        """Run baseline person detection on a BGR frame."""
        hog = self._ensure_hog()
        stride = config.vision.opencv_person_stride
        padding = config.vision.opencv_person_padding

        rects, weights = hog.detectMultiScale(
            frame_bgr,
            winStride=(stride, stride),
            padding=(padding, padding),
            scale=config.vision.opencv_person_scale,
        )

        boxes = []
        for index, (x, y, width, height) in enumerate(rects):
            raw_score = float(weights[index]) if len(weights) > index else 1.0
            score = 1 / (1 + math.exp(-raw_score))
            if score < config.vision.person_score_threshold:
                continue

            boxes.append(
                {
                    "id": f"person-{index + 1}",
                    "label": "person",
                    "score": round(score, 3),
                    "x1": int(x),
                    "y1": int(y),
                    "x2": int(x + width),
                    "y2": int(y + height),
                }
            )

        return self._sort_boxes(boxes)

    def detect_face(self, frame_bgr) -> list[dict]:
        """Run baseline face detection on a BGR frame."""
        face_cascade = self._ensure_face_cascade()
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        min_size = config.vision.opencv_face_min_size

        rects = face_cascade.detectMultiScale(
            gray,
            scaleFactor=config.vision.opencv_face_scale_factor,
            minNeighbors=config.vision.opencv_face_min_neighbors,
            minSize=(min_size, min_size),
        )

        boxes = []
        for index, (x, y, width, height) in enumerate(rects):
            score = 0.95
            if score < config.vision.face_score_threshold:
                continue

            boxes.append(
                {
                    "id": f"face-{index + 1}",
                    "label": "face",
                    "score": score,
                    "x1": int(x),
                    "y1": int(y),
                    "x2": int(x + width),
                    "y2": int(y + height),
                }
            )

        return self._sort_boxes(boxes)

    def close(self) -> None:
        """Release backend resources."""
        self._hog = None
        self._face_cascade = None
        return

    def _ensure_hog(self):
        if self._hog is not None:
            return self._hog

        if not hasattr(cv2, "HOGDescriptor"):
            raise RuntimeError("OpenCV build does not provide HOGDescriptor.")
        if not hasattr(cv2, "HOGDescriptor_getDefaultPeopleDetector"):
            raise RuntimeError("OpenCV build does not provide the default people detector.")

        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self._hog = hog
        return self._hog

    def _ensure_face_cascade(self):
        if self._face_cascade is not None:
            return self._face_cascade

        cascade_path = self._resolve_face_cascade_path()
        if cascade_path is None:
            raise RuntimeError("Could not find haarcascade_frontalface_default.xml on this system.")

        face_cascade = cv2.CascadeClassifier(str(cascade_path))
        if face_cascade.empty():
            raise RuntimeError(f"Failed to load OpenCV face cascade: {cascade_path}")

        self._face_cascade = face_cascade
        return self._face_cascade

    def _resolve_face_cascade_path(self) -> Path | None:
        candidate_paths = []

        if hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
            candidate_paths.append(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")

        candidate_paths.extend(
            [
                Path("/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"),
                Path("/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml"),
                Path("/usr/local/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"),
            ]
        )

        for path in candidate_paths:
            if path.is_file():
                return path

        return None

    def _sort_boxes(self, boxes: list[dict]) -> list[dict]:
        boxes.sort(
            key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]),
            reverse=True,
        )
        return boxes


def build_vision_backend():
    """Build the configured vision backend."""
    backend_name = config.vision.backend.lower().strip()

    if backend_name == "opencv":
        return OpenCvVisionBackend()
    if backend_name == "tflite":
        raise RuntimeError("TFLite backend is not implemented yet.")
    if backend_name in {"yolo", "yolo26n"}:
        raise RuntimeError("YOLO backend is not implemented yet.")

    raise RuntimeError(f"Unsupported vision backend: {config.vision.backend}")
