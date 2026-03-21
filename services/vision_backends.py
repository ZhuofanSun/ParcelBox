"""Backend implementations for vision detection."""

from __future__ import annotations

import math
from pathlib import Path

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

from config import config


class OpenCvVisionBackend:
    """OpenCV-based baseline backend for person and face detection."""

    name = "opencv"

    def __init__(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is not available. Install python3-opencv first.")
        if np is None:
            raise RuntimeError("NumPy is not available. Install numpy first.")

        self._hog = None
        self._person_detector = None
        self._face_cascade = None
        self._yunet_detector = None
        self._last_person_backend = config.vision.person_backend.lower().strip()
        self._last_face_backend = config.vision.face_backend.lower().strip()

    def detect_person(self, frame_bgr) -> list[dict]:
        """Run baseline person detection on a BGR frame."""
        preferred_backend = config.vision.person_backend.lower().strip()
        if preferred_backend == "hog":
            self._last_person_backend = "hog"
            return self._detect_person_with_hog(frame_bgr)
        if preferred_backend == "nanodet":
            try:
                self._last_person_backend = "nanodet"
                return self._detect_person_with_nanodet(frame_bgr)
            except Exception:
                if not config.vision.person_fallback_to_hog:
                    raise
                self._last_person_backend = "hog"
                return self._detect_person_with_hog(frame_bgr)

        try:
            self._last_person_backend = "mp_persondet"
            return self._detect_person_with_mp_persondet(frame_bgr)
        except Exception:
            if not config.vision.person_fallback_to_hog:
                raise
            self._last_person_backend = "hog"
            return self._detect_person_with_hog(frame_bgr)

    def detect_face(self, frame_bgr) -> list[dict]:
        """Run baseline face detection on a BGR frame."""
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
        self._hog = None
        self._person_detector = None
        self._face_cascade = None
        self._yunet_detector = None
        return

    def _detect_person_with_hog(self, frame_bgr) -> list[dict]:
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

    def _detect_person_with_mp_persondet(self, frame_bgr) -> list[dict]:
        detector = self._ensure_person_detector()
        return detector.detect(frame_bgr)

    def _detect_person_with_nanodet(self, frame_bgr) -> list[dict]:
        detector = self._ensure_person_detector()
        return detector.detect(frame_bgr)

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

    def _ensure_person_detector(self):
        if self._person_detector is not None:
            return self._person_detector

        model_path = self._resolve_local_path(config.vision.person_model_path)
        if not model_path.is_file():
            raise RuntimeError(
                f"Person detector model not found: {model_path}. "
                "Put the ONNX file in the configured models path."
            )

        preferred_backend = config.vision.person_backend.lower().strip()
        if preferred_backend == "nanodet":
            self._person_detector = NanoDetPersonDet(str(model_path))
        else:
            self._person_detector = MPPersonDet(str(model_path))
        return self._person_detector

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

        detector = self._create_yunet_detector(model_path)
        self._yunet_detector = detector
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

    def _sort_boxes(self, boxes: list[dict]) -> list[dict]:
        boxes.sort(
            key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]),
            reverse=True,
        )
        return boxes

    def get_runtime_info(self) -> dict:
        """Return lightweight runtime info for frontend debugging."""
        return {
            "person_backend_requested": config.vision.person_backend,
            "person_backend_active": self._last_person_backend,
            "person_model_path": config.vision.person_model_path,
            "face_backend_requested": config.vision.face_backend,
            "face_backend_active": self._last_face_backend,
            "face_model_path": config.vision.face_model_path,
        }


class NanoDetPersonDet:
    """OpenCV DNN wrapper for OpenCV Zoo NanoDet."""

    STRIDES = (8, 16, 32, 64)
    REG_MAX = 7
    PERSON_CLASS_ID = 0

    def __init__(self, model_path: str) -> None:
        self._input_width, self._input_height = config.vision.nanodet_input_size
        self._prob_threshold = config.vision.nanodet_prob_threshold
        self._iou_threshold = config.vision.nanodet_iou_threshold
        self._project = np.arange(self.REG_MAX + 1, dtype=np.float32)
        self._mean = np.array([103.53, 116.28, 123.675], dtype=np.float32).reshape(1, 1, 3)
        self._std = np.array([57.375, 57.12, 58.395], dtype=np.float32).reshape(1, 1, 3)
        self._net = cv2.dnn.readNet(model_path)
        self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self._anchors_mlvl = self._build_anchors()

    def detect(self, frame_bgr) -> list[dict]:
        """Run NanoDet and return person boxes in original frame coordinates."""
        frame_height, frame_width = frame_bgr.shape[:2]
        resized = cv2.resize(frame_bgr, (self._input_width, self._input_height))

        blob = self._preprocess(resized)
        self._net.setInput(blob)
        outputs = self._net.forward(self._net.getUnconnectedOutLayersNames())
        detections = self._post_process(outputs)
        if detections.size == 0:
            return []

        scale_x = frame_width / self._input_width
        scale_y = frame_height / self._input_height
        boxes = []

        for detection in detections:
            x1, y1, x2, y2, score, class_id = detection[:6]
            if int(class_id) != self.PERSON_CLASS_ID:
                continue
            if float(score) < config.vision.person_score_threshold:
                continue

            mapped_x1 = max(0, min(frame_width - 1, int(round(float(x1) * scale_x))))
            mapped_y1 = max(0, min(frame_height - 1, int(round(float(y1) * scale_y))))
            mapped_x2 = max(mapped_x1 + 1, min(frame_width, int(round(float(x2) * scale_x))))
            mapped_y2 = max(mapped_y1 + 1, min(frame_height, int(round(float(y2) * scale_y))))

            boxes.append(
                {
                    "id": f"person-{len(boxes) + 1}",
                    "label": "person",
                    "score": round(float(score), 3),
                    "x1": mapped_x1,
                    "y1": mapped_y1,
                    "x2": mapped_x2,
                    "y2": mapped_y2,
                }
            )

        boxes.sort(
            key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]),
            reverse=True,
        )
        return boxes[: config.vision.person_max_results]

    def _preprocess(self, resized_bgr):
        normalized = resized_bgr.astype(np.float32)
        normalized = (normalized - self._mean) / self._std
        return cv2.dnn.blobFromImage(normalized)

    def _post_process(self, preds) -> np.ndarray:
        cls_scores = preds[::2]
        bbox_preds = preds[1::2]
        bboxes_mlvl = []
        scores_mlvl = []

        for stride, cls_score, bbox_pred, anchors in zip(
            self.STRIDES,
            cls_scores,
            bbox_preds,
            self._anchors_mlvl,
        ):
            cls_score = self._squeeze_to_2d(cls_score)
            bbox_pred = self._squeeze_to_2d(bbox_pred)

            x_exp = np.exp(bbox_pred.reshape(-1, self.REG_MAX + 1))
            x_sum = np.sum(x_exp, axis=1, keepdims=True)
            bbox_pred = x_exp / x_sum
            bbox_pred = np.dot(bbox_pred, self._project).reshape(-1, 4)
            bbox_pred *= stride

            nms_pre = 1000
            if nms_pre > 0 and cls_score.shape[0] > nms_pre:
                max_scores = cls_score.max(axis=1)
                topk_inds = max_scores.argsort()[::-1][:nms_pre]
                anchors = anchors[topk_inds, :]
                bbox_pred = bbox_pred[topk_inds, :]
                cls_score = cls_score[topk_inds, :]

            x1 = anchors[:, 0] - bbox_pred[:, 0]
            y1 = anchors[:, 1] - bbox_pred[:, 1]
            x2 = anchors[:, 0] + bbox_pred[:, 2]
            y2 = anchors[:, 1] + bbox_pred[:, 3]

            x1 = np.clip(x1, 0, self._input_width)
            y1 = np.clip(y1, 0, self._input_height)
            x2 = np.clip(x2, 0, self._input_width)
            y2 = np.clip(y2, 0, self._input_height)

            bboxes = np.column_stack([x1, y1, x2, y2])
            bboxes_mlvl.append(bboxes)
            scores_mlvl.append(cls_score)

        if not bboxes_mlvl:
            return np.array([])

        bboxes_mlvl = np.concatenate(bboxes_mlvl, axis=0)
        scores_mlvl = np.concatenate(scores_mlvl, axis=0)
        bboxes_wh = bboxes_mlvl.copy()
        bboxes_wh[:, 2:4] = bboxes_wh[:, 2:4] - bboxes_wh[:, 0:2]

        class_ids = np.argmax(scores_mlvl, axis=1)
        confidences = np.max(scores_mlvl, axis=1)

        person_mask = class_ids == self.PERSON_CLASS_ID
        if not np.any(person_mask):
            return np.array([])

        person_boxes = bboxes_wh[person_mask]
        person_boxes_xyxy = bboxes_mlvl[person_mask]
        person_scores = confidences[person_mask]
        person_class_ids = class_ids[person_mask]

        indices = cv2.dnn.NMSBoxes(
            person_boxes.tolist(),
            person_scores.tolist(),
            self._prob_threshold,
            self._iou_threshold,
        )

        if indices is None or len(indices) == 0:
            return np.array([])

        flat_indices = np.array(indices).reshape(-1)
        kept_boxes = person_boxes_xyxy[flat_indices]
        kept_scores = person_scores[flat_indices]
        kept_class_ids = person_class_ids[flat_indices]
        return np.concatenate(
            [kept_boxes, kept_scores.reshape(-1, 1), kept_class_ids.reshape(-1, 1)],
            axis=1,
        )

    def _build_anchors(self) -> list[np.ndarray]:
        anchors_mlvl = []
        for stride in self.STRIDES:
            feat_h = int(self._input_height / stride)
            feat_w = int(self._input_width / stride)
            shift_x = np.arange(0, feat_w, dtype=np.float32) * stride
            shift_y = np.arange(0, feat_h, dtype=np.float32) * stride
            xv, yv = np.meshgrid(shift_x, shift_y)
            cx = xv.flatten() + 0.5 * (stride - 1)
            cy = yv.flatten() + 0.5 * (stride - 1)
            anchors_mlvl.append(np.column_stack((cx, cy)))
        return anchors_mlvl

    def _squeeze_to_2d(self, array) -> np.ndarray:
        normalized = np.asarray(array).squeeze()
        if normalized.ndim == 1:
            return normalized.reshape(-1, 1)
        return normalized


class MPPersonDet:
    """OpenCV DNN wrapper for OpenCV Zoo MP-PersonDet."""

    INPUT_WIDTH = 224
    INPUT_HEIGHT = 224
    STRIDES = [8, 16, 32, 32, 32]
    MIN_SCALE = 0.1484375
    MAX_SCALE = 0.75
    ASPECT_RATIOS = [1.0]
    INTERPOLATED_SCALE_ASPECT_RATIO = 1.0

    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        self._net = cv2.dnn.readNet(model_path)
        self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self._anchors = self._generate_anchors()

    def detect(self, frame_bgr) -> list[dict]:
        """Run MP-PersonDet and return person boxes in original frame coordinates."""
        blob, scale, pad_x, pad_y = self._preprocess(frame_bgr)
        self._net.setInput(blob)
        outputs = self._net.forward(self._net.getUnconnectedOutLayersNames())
        raw_boxes, raw_scores = self._split_outputs(outputs)

        count = min(len(raw_boxes), len(raw_scores), len(self._anchors))
        if count == 0:
            return []

        raw_boxes = raw_boxes[:count]
        raw_scores = raw_scores[:count]
        anchors = self._anchors[:count]
        clipped_scores = np.clip(raw_scores, -60.0, 60.0)
        scores = 1.0 / (1.0 + np.exp(-clipped_scores))

        frame_height, frame_width = frame_bgr.shape[:2]
        score_threshold = config.vision.mp_persondet_score_threshold
        nms_threshold = config.vision.mp_persondet_nms_threshold
        top_k = config.vision.mp_persondet_top_k

        candidates = []
        nms_boxes = []
        nms_scores = []

        for index, score in enumerate(scores):
            score_value = float(score)
            if score_value < score_threshold:
                continue

            box = raw_boxes[index]
            anchor = anchors[index]

            center_x = (float(box[0]) + anchor[0] * self.INPUT_WIDTH) / self.INPUT_WIDTH
            center_y = (float(box[1]) + anchor[1] * self.INPUT_HEIGHT) / self.INPUT_HEIGHT
            width = float(box[2]) / self.INPUT_WIDTH
            height = float(box[3]) / self.INPUT_HEIGHT

            x1 = (center_x - width * 0.5) * self.INPUT_WIDTH
            y1 = (center_y - height * 0.5) * self.INPUT_HEIGHT
            x2 = (center_x + width * 0.5) * self.INPUT_WIDTH
            y2 = (center_y + height * 0.5) * self.INPUT_HEIGHT

            x1 = (x1 - pad_x) / scale
            y1 = (y1 - pad_y) / scale
            x2 = (x2 - pad_x) / scale
            y2 = (y2 - pad_y) / scale

            x1 = max(0, min(frame_width - 1, int(round(x1))))
            y1 = max(0, min(frame_height - 1, int(round(y1))))
            x2 = max(x1 + 1, min(frame_width, int(round(x2))))
            y2 = max(y1 + 1, min(frame_height, int(round(y2))))

            box_width = x2 - x1
            box_height = y2 - y1
            if box_width <= 1 or box_height <= 1:
                continue

            candidates.append(
                {
                    "id": f"person-{len(candidates) + 1}",
                    "label": "person",
                    "score": round(score_value, 3),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )
            nms_boxes.append([x1, y1, box_width, box_height])
            nms_scores.append(score_value)

        if not candidates:
            return []

        selected = self._nms(nms_boxes, nms_scores, score_threshold, nms_threshold, top_k)
        boxes = [candidates[index] for index in selected[: config.vision.person_max_results]]
        boxes.sort(
            key=lambda box: (box["x2"] - box["x1"]) * (box["y2"] - box["y1"]),
            reverse=True,
        )
        return boxes

    def _preprocess(self, frame_bgr):
        frame_height, frame_width = frame_bgr.shape[:2]
        scale = min(self.INPUT_WIDTH / frame_width, self.INPUT_HEIGHT / frame_height)
        resized_width = max(1, int(round(frame_width * scale)))
        resized_height = max(1, int(round(frame_height * scale)))

        resized = cv2.resize(frame_bgr, (resized_width, resized_height))

        pad_x = (self.INPUT_WIDTH - resized_width) / 2.0
        pad_y = (self.INPUT_HEIGHT - resized_height) / 2.0
        left = int(math.floor(pad_x))
        right = int(math.ceil(pad_x))
        top = int(math.floor(pad_y))
        bottom = int(math.ceil(pad_y))

        padded = cv2.copyMakeBorder(
            resized,
            top,
            bottom,
            left,
            right,
            cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        )
        blob = cv2.dnn.blobFromImage(
            padded,
            scalefactor=1.0 / 127.5,
            size=(self.INPUT_WIDTH, self.INPUT_HEIGHT),
            mean=(127.5, 127.5, 127.5),
            swapRB=True,
            crop=False,
        )
        return blob, scale, float(left), float(top)

    def _split_outputs(self, outputs) -> tuple[np.ndarray, np.ndarray]:
        arrays = outputs if isinstance(outputs, (list, tuple)) else [outputs]
        box_blob = None
        score_blob = None

        for array in arrays:
            normalized = self._normalize_output(array)
            if normalized.ndim != 2:
                continue

            if normalized.shape[1] == 1:
                score_blob = normalized[:, 0]
            elif normalized.shape[1] >= 4:
                box_blob = normalized

        if box_blob is None or score_blob is None:
            raise RuntimeError("Unexpected MP-PersonDet output shapes from OpenCV DNN.")

        return box_blob.astype(np.float32), score_blob.astype(np.float32)

    def _normalize_output(self, array) -> np.ndarray:
        normalized = np.asarray(array).squeeze()
        if normalized.ndim == 1:
            return normalized.reshape(-1, 1)
        if normalized.ndim != 2:
            return normalized
        if normalized.shape[0] <= 16 and normalized.shape[1] > normalized.shape[0]:
            return normalized.transpose()
        return normalized

    def _nms(
        self,
        boxes: list[list[int]],
        scores: list[float],
        score_threshold: float,
        nms_threshold: float,
        top_k: int,
    ) -> list[int]:
        try:
            indices = cv2.dnn.NMSBoxes(
                boxes,
                scores,
                score_threshold,
                nms_threshold,
                top_k=top_k,
            )
        except TypeError:
            indices = cv2.dnn.NMSBoxes(
                boxes,
                scores,
                score_threshold,
                nms_threshold,
            )

        if indices is None or len(indices) == 0:
            return []

        return [int(index) for index in np.array(indices).reshape(-1)]

    def _generate_anchors(self) -> np.ndarray:
        anchors: list[list[float]] = []
        num_layers = len(self.STRIDES)
        layer_id = 0

        while layer_id < num_layers:
            anchor_widths: list[float] = []
            anchor_heights: list[float] = []
            aspect_ratios: list[float] = []
            scales: list[float] = []

            last_same_stride_layer = layer_id
            while (
                last_same_stride_layer < num_layers
                and self.STRIDES[last_same_stride_layer] == self.STRIDES[layer_id]
            ):
                scale = self._calculate_scale(last_same_stride_layer, num_layers)
                for aspect_ratio in self.ASPECT_RATIOS:
                    aspect_ratios.append(aspect_ratio)
                    scales.append(scale)

                scale_next = (
                    1.0
                    if last_same_stride_layer == num_layers - 1
                    else self._calculate_scale(last_same_stride_layer + 1, num_layers)
                )
                aspect_ratios.append(self.INTERPOLATED_SCALE_ASPECT_RATIO)
                scales.append(math.sqrt(scale * scale_next))
                last_same_stride_layer += 1

            for aspect_ratio, scale in zip(aspect_ratios, scales):
                ratio_sqrt = math.sqrt(aspect_ratio)
                anchor_heights.append(scale / ratio_sqrt)
                anchor_widths.append(scale * ratio_sqrt)

            stride = self.STRIDES[layer_id]
            feature_map_height = math.ceil(self.INPUT_HEIGHT / stride)
            feature_map_width = math.ceil(self.INPUT_WIDTH / stride)

            for y in range(feature_map_height):
                y_center = (y + 0.5) / feature_map_height
                for x in range(feature_map_width):
                    x_center = (x + 0.5) / feature_map_width
                    for _ in range(len(anchor_widths)):
                        anchors.append([x_center, y_center, 1.0, 1.0])

            layer_id = last_same_stride_layer

        return np.asarray(anchors, dtype=np.float32)

    def _calculate_scale(self, stride_index: int, num_strides: int) -> float:
        if num_strides == 1:
            return (self.MIN_SCALE + self.MAX_SCALE) * 0.5
        return self.MIN_SCALE + (self.MAX_SCALE - self.MIN_SCALE) * stride_index / (num_strides - 1)


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
