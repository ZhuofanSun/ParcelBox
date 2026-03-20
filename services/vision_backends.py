"""Backend implementations for vision detection."""

from __future__ import annotations

import math

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

        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._face_cascade = cv2.CascadeClassifier(cascade_path)
        if self._face_cascade.empty():
            raise RuntimeError(f"Failed to load OpenCV face cascade: {cascade_path}")

    def detect_person(self, frame_bgr) -> list[dict]:
        """Run baseline person detection on a BGR frame."""
        stride = config.vision.opencv_person_stride
        padding = config.vision.opencv_person_padding

        rects, weights = self._hog.detectMultiScale(
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
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        min_size = config.vision.opencv_face_min_size

        rects = self._face_cascade.detectMultiScale(
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
        return

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
