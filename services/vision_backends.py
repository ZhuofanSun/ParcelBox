"""Backend implementations for face detection."""

from __future__ import annotations

from pathlib import Path

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

from config import config


class OpenCvVisionBackend:
    """OpenCV-based backend for face detection."""

    name = "opencv"

    def __init__(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is not available. Install python3-opencv first.")

        self._face_cascade = None
        self._yunet_detector = None
        self._last_face_backend = config.vision.face_backend.lower().strip()

    def detect_face(self, frame_bgr) -> list[dict]:
        """Run face detection on a BGR frame."""
        preferred_backend = config.vision.face_backend.lower().strip()
        if preferred_backend == "haar":
            self._last_face_backend = "haar"
            return self._detect_face_with_haar(frame_bgr)

        try:
            self._last_face_backend = "yunet"
            return self._detect_face_with_yunet(frame_bgr)
        except Exception:
            if not config.vision.face_fallback_to_haar:
                raise
            self._last_face_backend = "haar"
            return self._detect_face_with_haar(frame_bgr)

    def close(self) -> None:
        """Release backend resources."""
        self._face_cascade = None
        self._yunet_detector = None

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

    def _detect_face_with_haar(self, frame_bgr) -> list[dict]:
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

    def _detect_face_with_yunet(self, frame_bgr) -> list[dict]:
        detector = self._ensure_yunet_detector()
        input_height, input_width = frame_bgr.shape[:2]
        detector.setInputSize((input_width, input_height))

        _, faces = detector.detect(frame_bgr)
        if faces is None or len(faces) == 0:
            return []

        boxes = []
        for index, face in enumerate(faces):
            x, y, width, height = face[:4]
            score = float(face[-1])
            if score < config.vision.face_score_threshold:
                continue

            x1 = int(max(0, round(x)))
            y1 = int(max(0, round(y)))
            x2 = int(max(x1 + 1, round(x + width)))
            y2 = int(max(y1 + 1, round(y + height)))

            boxes.append(
                {
                    "id": f"face-{index + 1}",
                    "label": "face",
                    "score": round(score, 3),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )

        return self._sort_boxes(boxes)

    def _ensure_yunet_detector(self):
        if self._yunet_detector is not None:
            return self._yunet_detector

        model_path = self._resolve_local_path(config.vision.face_model_path)
        if not model_path.is_file():
            raise RuntimeError(
                f"YuNet model not found: {model_path}. "
                "Put the ONNX file in the configured models path."
            )

        self._yunet_detector = self._create_yunet_detector(model_path)
        return self._yunet_detector

    def _create_yunet_detector(self, model_path: Path):
        score_threshold = config.vision.yunet_score_threshold
        nms_threshold = config.vision.yunet_nms_threshold
        top_k = config.vision.yunet_top_k
        input_size = config.camera.detection_size

        if hasattr(cv2, "FaceDetectorYN") and hasattr(cv2.FaceDetectorYN, "create"):
            try:
                return cv2.FaceDetectorYN.create(
                    str(model_path),
                    "",
                    input_size,
                    score_threshold,
                    nms_threshold,
                    top_k,
                )
            except TypeError:
                return cv2.FaceDetectorYN.create(
                    str(model_path),
                    "",
                    input_size,
                    score_threshold,
                    nms_threshold,
                    top_k,
                    0,
                    0,
                )

        if hasattr(cv2, "FaceDetectorYN_create"):
            try:
                return cv2.FaceDetectorYN_create(
                    str(model_path),
                    "",
                    input_size,
                    score_threshold,
                    nms_threshold,
                    top_k,
                )
            except TypeError:
                return cv2.FaceDetectorYN_create(
                    str(model_path),
                    "",
                    input_size,
                    score_threshold,
                    nms_threshold,
                    top_k,
                    0,
                    0,
                )

        raise RuntimeError("This OpenCV build does not provide FaceDetectorYN / YuNet.")

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

    def _resolve_local_path(self, path: str) -> Path:
        local_path = Path(path)
        if not local_path.is_absolute():
            local_path = Path(__file__).resolve().parent.parent / local_path
        return local_path

    @staticmethod
    def _sort_boxes(boxes: list[dict]) -> list[dict]:
        boxes.sort(
            key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]),
            reverse=True,
        )
        return boxes

    def get_runtime_info(self) -> dict:
        """Return lightweight runtime info for frontend debugging."""
        return {
            "face_backend_requested": config.vision.face_backend,
            "face_backend_active": self._last_face_backend,
            "face_model_path": config.vision.face_model_path,
        }


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
