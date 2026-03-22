from __future__ import annotations

import copy
import unittest

from config import config
from services.vision_service import VisionService


class FakeVisionCamera:
    def get_detection_frame_bgr(self):
        return "fake-frame"


class FakeFaceBackend:
    def __init__(self, detections: list[list[dict]]) -> None:
        self._detections = [copy.deepcopy(item) for item in detections]

    def detect_face(self, frame_bgr) -> list[dict]:
        if not self._detections:
            return []
        return self._detections.pop(0)

    def get_runtime_info(self) -> dict:
        return {"face_backend_active": "fake"}


def build_detection_face_box(x1: int, y1: int, x2: int, y2: int) -> dict:
    return {
        "id": "face-1",
        "label": "face",
        "score": 0.95,
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
    }


class VisionServiceFaceOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)

    def tearDown(self) -> None:
        config.gpio = self.original_config.gpio
        config.camera = self.original_config.camera
        config.camera_mount = self.original_config.camera_mount
        config.door = self.original_config.door
        config.rfid = self.original_config.rfid
        config.ultrasonic = self.original_config.ultrasonic
        config.storage = self.original_config.storage
        config.email = self.original_config.email
        config.vision = self.original_config.vision
        config.web = self.original_config.web

    def test_run_detection_cycle_reports_face_mode(self) -> None:
        service = VisionService(FakeVisionCamera())
        service._backend = FakeFaceBackend([[build_detection_face_box(100, 80, 220, 220)]])

        payload = service._run_detection_cycle()

        self.assertEqual(payload["mode"], "face")
        self.assertEqual(payload["active_mode"], "face")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target"]["label"], "face")
        self.assertEqual(payload["runtime"]["current_detection_fps_target"], config.vision.detection_fps)

    def test_run_detection_cycle_keeps_short_face_hold(self) -> None:
        config.vision.face_hold_frames = 2
        service = VisionService(FakeVisionCamera())
        service._backend = FakeFaceBackend(
            [
                [build_detection_face_box(100, 80, 220, 220)],
                [],
            ]
        )

        first_payload = service._run_detection_cycle()
        second_payload = service._run_detection_cycle()

        self.assertEqual(first_payload["active_mode"], "face")
        self.assertEqual(second_payload["active_mode"], "face_hold")
        self.assertIsNotNone(second_payload["target"])
        self.assertEqual(second_payload["target"]["label"], "face")

    def test_run_detection_cycle_smooths_primary_face_box(self) -> None:
        config.camera.stream_size = (640, 360)
        config.camera.detection_size = (640, 360)
        config.vision.face_box_smoothing = 0.25
        service = VisionService(FakeVisionCamera())
        service._backend = FakeFaceBackend(
            [
                [build_detection_face_box(100, 80, 220, 220)],
                [build_detection_face_box(180, 100, 300, 240)],
            ]
        )

        first_payload = service._run_detection_cycle()
        second_payload = service._run_detection_cycle()

        self.assertEqual(first_payload["boxes"][0]["x1"], 100)
        self.assertEqual(second_payload["active_mode"], "face")
        self.assertGreater(second_payload["boxes"][0]["x1"], 100)
        self.assertLess(second_payload["boxes"][0]["x1"], 180)
        self.assertGreater(second_payload["target"]["center_x"], 160.0)
        self.assertLess(second_payload["target"]["center_x"], 240.0)


if __name__ == "__main__":
    unittest.main()
