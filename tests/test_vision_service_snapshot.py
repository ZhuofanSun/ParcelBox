from __future__ import annotations

import copy
import unittest

from config import config
from services.vision_service import VisionService


class FakeVisionCamera:
    def __init__(self) -> None:
        self.snapshots: list[dict] = []

    def capture_snapshot(self) -> dict:
        snapshot = {
            "path": f"/tmp/vision_snapshot_{len(self.snapshots) + 1}.jpg",
            "saved_at": "2026-03-21T12:00:00",
        }
        self.snapshots.append(copy.deepcopy(snapshot))
        return snapshot


def build_face_box(x1: int, y1: int, x2: int, y2: int) -> dict:
    return {
        "id": "face-1",
        "label": "face",
        "score": 0.95,
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
    }


class VisionServiceSnapshotTests(unittest.TestCase):
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
        config.vision = self.original_config.vision
        config.web = self.original_config.web

    def test_large_face_captures_once_until_faces_disappear(self) -> None:
        camera = FakeVisionCamera()
        service = VisionService(camera)
        config.camera.stream_size = (1280, 720)
        config.vision.face_snapshot_trigger_area_ratio = 0.1
        large_face = build_face_box(220, 80, 680, 560)

        service._maybe_capture_face_snapshot([large_face])
        service._maybe_capture_face_snapshot([large_face])
        service._maybe_capture_face_snapshot([])
        service._maybe_capture_face_snapshot([large_face])

        self.assertEqual(len(camera.snapshots), 2)

    def test_small_face_does_not_trigger_snapshot(self) -> None:
        camera = FakeVisionCamera()
        service = VisionService(camera)
        config.camera.stream_size = (1280, 720)
        config.vision.face_snapshot_trigger_area_ratio = 0.1
        small_face = build_face_box(100, 100, 220, 220)

        service._maybe_capture_face_snapshot([small_face])

        self.assertEqual(camera.snapshots, [])


if __name__ == "__main__":
    unittest.main()
