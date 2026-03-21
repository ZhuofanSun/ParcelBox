from __future__ import annotations

import copy
import unittest

from config import config
from services.camera_mount_service import CameraMountService


def build_payload(
    *,
    center_x: float | None = 640,
    center_y: float | None = 360,
    status: str = "ok",
    width: int = 1280,
    height: int = 720,
) -> dict:
    target = None
    if center_x is not None and center_y is not None:
        target = {
            "id": "face-1",
            "label": "face",
            "center_x": center_x,
            "center_y": center_y,
        }

    return {
        "status": status,
        "frame_size": {
            "width": width,
            "height": height,
        },
        "target": target,
        "boxes": [],
    }


class CameraMountServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_mount_config = copy.deepcopy(config.camera_mount)

    def tearDown(self) -> None:
        config.camera_mount = self.original_mount_config

    def test_centered_target_returns_centered_advice(self) -> None:
        service = CameraMountService()
        service.start()

        service.enrich_payload(build_payload())
        payload = service.enrich_payload(build_payload())
        advice = payload["camera_mount"]

        self.assertEqual(advice["status"], "centered")
        self.assertEqual(advice["direction"], "centered")
        self.assertEqual(advice["pan"]["direction"], "hold")
        self.assertEqual(advice["tilt"]["direction"], "hold")
        self.assertEqual(advice["distance_ratio"], 0.0)
        self.assertEqual(advice["tracking_label"], "face")

    def test_off_center_target_returns_axis_directions_with_pan_inversion(self) -> None:
        service = CameraMountService()
        service.start()

        service.enrich_payload(build_payload(center_x=980, center_y=200))
        payload = service.enrich_payload(build_payload(center_x=980, center_y=200))
        advice = payload["camera_mount"]

        self.assertEqual(advice["status"], "tracking")
        self.assertEqual(advice["pan"]["direction"], "left")
        self.assertEqual(advice["tilt"]["direction"], "up")
        self.assertEqual(advice["direction"], "up-left")
        self.assertGreater(advice["distance_ratio"], 0.0)

    def test_person_target_after_face_tracking_triggers_home(self) -> None:
        service = CameraMountService()
        service.start()

        service.enrich_payload(build_payload())
        service.enrich_payload(build_payload())
        payload = service.enrich_payload(
            {
                "status": "ok",
                "frame_size": {"width": 1280, "height": 720},
                "target": {
                    "id": "person-1",
                    "label": "person",
                    "center_x": 900,
                    "center_y": 360,
                },
                "boxes": [
                    {
                        "id": "person-1",
                        "label": "person",
                        "x1": 700,
                        "y1": 100,
                        "x2": 1100,
                        "y2": 650,
                    }
                ],
            }
        )
        advice = payload["camera_mount"]

        self.assertEqual(advice["status"], "returning_home")
        self.assertEqual(advice["home_reason"], "face_lost")
        self.assertFalse(advice["has_target"])
        self.assertEqual(advice["direction"], "home")

    def test_missing_target_returns_waiting_for_face_after_home(self) -> None:
        service = CameraMountService()
        service.start()

        service.enrich_payload(build_payload(center_x=None, center_y=None))
        payload = service.enrich_payload(build_payload(center_x=None, center_y=None))
        advice = payload["camera_mount"]

        self.assertEqual(advice["status"], "waiting_for_face")
        self.assertFalse(advice["has_target"])
        self.assertEqual(advice["direction"], "hold")

    def test_startup_requests_home_first(self) -> None:
        service = CameraMountService()
        service.start()

        payload = service.enrich_payload(build_payload())
        advice = payload["camera_mount"]

        self.assertEqual(advice["status"], "returning_home")
        self.assertEqual(advice["home_reason"], "startup")
        self.assertTrue(advice["should_home"])

    def test_status_exposes_latest_advice(self) -> None:
        service = CameraMountService()
        service.start()
        service.enrich_payload(build_payload(center_x=800, center_y=500))
        service.enrich_payload(build_payload(center_x=800, center_y=500))

        status = service.get_status()
        self.assertTrue(status["started"])
        self.assertIn("latest_advice", status)
        self.assertTrue(status["direction_inversion"]["pan"])
        self.assertEqual(status["latest_advice"]["pan"]["direction"], "left")


if __name__ == "__main__":
    unittest.main()
