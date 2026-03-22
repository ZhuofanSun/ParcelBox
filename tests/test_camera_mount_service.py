from __future__ import annotations

import copy
import time
import unittest
from unittest.mock import patch

from config import config
from services.camera_mount_service import CameraMountService


class FakeServo:
    def __init__(self, pin: int, min_angle: float = 0, max_angle: float = 180, **kwargs) -> None:
        self.pin = pin
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.current_angle = None
        self.moves: list[dict] = []
        self.set_angle_calls: list[dict] = []
        self.release_calls = 0
        self.cleaned_up = False

    def move_to(self, angle: float, step: float = 1, delay: float = 0.02, release: bool = True) -> None:
        if not self.min_angle <= angle <= self.max_angle:
            raise ValueError("angle out of range")
        self.current_angle = angle
        self.moves.append(
            {
                "angle": angle,
                "step": step,
                "delay": delay,
                "release": release,
            }
        )

    def set_angle(self, angle: float, settle_time: float = 0.3, release: bool = True) -> None:
        if not self.min_angle <= angle <= self.max_angle:
            raise ValueError("angle out of range")
        self.current_angle = angle
        self.set_angle_calls.append(
            {
                "angle": angle,
                "settle_time": settle_time,
                "release": release,
            }
        )
        if release:
            self.release()

    def release(self) -> None:
        self.release_calls += 1

    def cleanup(self) -> None:
        self.cleaned_up = True


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
        self.sleep_patcher = patch("services.camera_mount_service.time.sleep", return_value=None)
        self.sleep_patcher.start()
        config.camera_mount.invert_pan_direction = True
        config.camera_mount.invert_tilt_direction = False

    def tearDown(self) -> None:
        self.sleep_patcher.stop()
        config.camera_mount = self.original_mount_config

    def build_service(self) -> CameraMountService:
        service = CameraMountService(servo_factory=FakeServo)
        service.start()
        self.addCleanup(service.stop)
        return service

    def test_centered_target_returns_centered_advice(self) -> None:
        service = self.build_service()

        service._process_payload(build_payload())
        advice = service._process_payload(build_payload())

        self.assertEqual(advice["status"], "centered")
        self.assertEqual(advice["direction"], "centered")
        self.assertEqual(advice["pan"]["direction"], "hold")
        self.assertEqual(advice["tilt"]["direction"], "hold")
        self.assertEqual(advice["pan"]["move_angle"], 0.0)
        self.assertEqual(advice["tilt"]["move_angle"], 0.0)
        self.assertEqual(advice["distance_ratio"], 0.0)
        self.assertEqual(advice["tracking_label"], "face")
        self.assertEqual(service.get_status()["current_angles"]["pan"], config.camera_mount.pan_home_angle)
        self.assertEqual(service.get_status()["current_angles"]["tilt"], config.camera_mount.tilt_home_angle)

    def test_off_center_target_returns_axis_directions_with_pan_inversion(self) -> None:
        service = self.build_service()

        service._process_payload(build_payload())
        advice = service._process_payload(build_payload(center_x=980, center_y=200))

        self.assertEqual(advice["status"], "tracking")
        self.assertEqual(advice["pan"]["direction"], "left")
        self.assertEqual(advice["tilt"]["direction"], "up")
        self.assertGreater(advice["pan"]["move_angle"], 0.0)
        self.assertGreater(advice["tilt"]["move_angle"], 0.0)
        self.assertLessEqual(advice["pan"]["move_angle"], config.camera_mount.pan_max_single_move_angle)
        self.assertLessEqual(advice["tilt"]["move_angle"], config.camera_mount.tilt_max_single_move_angle)
        self.assertEqual(advice["direction"], "up-left")
        self.assertGreater(advice["distance_ratio"], 0.0)
        self.assertLess(service.get_status()["current_angles"]["pan"], config.camera_mount.pan_home_angle)
        self.assertLess(service.get_status()["current_angles"]["tilt"], config.camera_mount.tilt_home_angle)

    def test_person_target_after_face_tracking_triggers_home(self) -> None:
        service = self.build_service()

        service._process_payload(build_payload())
        service._process_payload(build_payload(center_x=980, center_y=200))
        advice = service._process_payload(
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

        self.assertEqual(advice["status"], "returning_home")
        self.assertEqual(advice["home_reason"], "face_lost")
        self.assertFalse(advice["has_target"])
        self.assertEqual(advice["direction"], "home")
        self.assertEqual(advice["pan"]["move_angle"], 0.0)
        self.assertEqual(advice["tilt"]["move_angle"], 0.0)
        self.assertEqual(service.get_status()["current_angles"]["pan"], config.camera_mount.pan_home_angle)
        self.assertEqual(service.get_status()["current_angles"]["tilt"], config.camera_mount.tilt_home_angle)

    def test_missing_target_returns_waiting_for_face_after_home(self) -> None:
        service = self.build_service()

        service._process_payload(build_payload(center_x=None, center_y=None))
        advice = service._process_payload(build_payload(center_x=None, center_y=None))

        self.assertEqual(advice["status"], "waiting_for_face")
        self.assertFalse(advice["has_target"])
        self.assertEqual(advice["direction"], "hold")
        self.assertEqual(advice["pan"]["move_angle"], 0.0)
        self.assertEqual(advice["tilt"]["move_angle"], 0.0)

    def test_missing_face_periodically_triggers_home_fallback(self) -> None:
        service = self.build_service()

        service._process_payload(build_payload())
        service._last_home_issue_at = time.monotonic() - (
            config.camera_mount.no_face_home_interval_seconds + 0.1
        )

        advice = service._process_payload(build_payload(center_x=None, center_y=None))

        self.assertEqual(advice["status"], "returning_home")
        self.assertEqual(advice["home_reason"], "no_face_idle")
        self.assertTrue(advice["should_home"])
        self.assertEqual(service.get_status()["current_angles"]["pan"], config.camera_mount.pan_home_angle)
        self.assertEqual(service.get_status()["current_angles"]["tilt"], config.camera_mount.tilt_home_angle)

    def test_startup_requests_home_first(self) -> None:
        service = self.build_service()

        advice = service._process_payload(build_payload())

        self.assertEqual(advice["status"], "returning_home")
        self.assertEqual(advice["home_reason"], "startup")
        self.assertTrue(advice["should_home"])
        self.assertEqual(advice["pan"]["move_angle"], 0.0)
        self.assertEqual(advice["tilt"]["move_angle"], 0.0)
        self.assertEqual(service.get_status()["current_angles"]["pan"], config.camera_mount.pan_home_angle)
        self.assertEqual(service.get_status()["current_angles"]["tilt"], config.camera_mount.tilt_home_angle)

    def test_status_exposes_latest_advice(self) -> None:
        service = self.build_service()
        service._process_payload(build_payload())
        service._process_payload(build_payload(center_x=800, center_y=500))

        status = service.get_status()
        self.assertTrue(status["started"])
        self.assertIn("latest_advice", status)
        self.assertTrue(status["direction_inversion"]["pan"])
        self.assertEqual(status["latest_advice"]["pan"]["direction"], "left")
        self.assertTrue(status["servo_control_enabled"])
        self.assertIsNone(status["last_error"])

    def test_move_angle_scales_up_and_caps_at_single_move_limit(self) -> None:
        service = self.build_service()

        service._process_payload(build_payload())
        near = service._process_payload(build_payload(center_x=780, center_y=360))
        far = service._process_payload(build_payload(center_x=1200, center_y=360))
        edge = service._process_payload(build_payload(center_x=1280, center_y=360))

        self.assertGreater(far["pan"]["move_angle"], near["pan"]["move_angle"])
        self.assertEqual(edge["pan"]["move_angle"], config.camera_mount.pan_max_single_move_angle)

    def test_duplicate_detection_version_moves_only_once(self) -> None:
        service = self.build_service()
        config.camera_mount.tracking_cooldown_seconds = 0.0

        service._process_payload(build_payload(), version=1)
        service._process_payload(build_payload(center_x=980, center_y=200), version=2)
        first_pan_moves = len(service._pan_servo.set_angle_calls)
        first_tilt_moves = len(service._tilt_servo.set_angle_calls)

        service._process_payload(build_payload(center_x=980, center_y=200), version=2)

        self.assertEqual(len(service._pan_servo.set_angle_calls), first_pan_moves)
        self.assertEqual(len(service._tilt_servo.set_angle_calls), first_tilt_moves)

    def test_tracking_cooldown_blocks_immediate_second_move(self) -> None:
        service = self.build_service()
        config.camera_mount.tracking_cooldown_seconds = 60.0

        service._process_payload(build_payload())
        service._process_payload(build_payload(center_x=980, center_y=200), version=2)
        first_pan_angle = service.get_status()["current_angles"]["pan"]
        first_tilt_angle = service.get_status()["current_angles"]["tilt"]
        first_pan_moves = len(service._pan_servo.set_angle_calls)
        first_tilt_moves = len(service._tilt_servo.set_angle_calls)

        advice = service._process_payload(build_payload(center_x=1120, center_y=140), version=3)

        self.assertEqual(advice["status"], "tracking")
        self.assertEqual(len(service._pan_servo.set_angle_calls), first_pan_moves)
        self.assertEqual(len(service._tilt_servo.set_angle_calls), first_tilt_moves)
        self.assertEqual(service.get_status()["current_angles"]["pan"], first_pan_angle)
        self.assertEqual(service.get_status()["current_angles"]["tilt"], first_tilt_angle)

    def test_tracking_move_uses_minimum_step_and_maximum_delay(self) -> None:
        service = self.build_service()
        config.camera_mount.tracking_step = 0.2
        config.camera_mount.tracking_delay = 0.3

        service._process_payload(build_payload())
        service._process_payload(build_payload(center_x=980, center_y=200), version=2)

        self.assertEqual(service._movement_step(), 1.0)
        self.assertEqual(service._movement_delay(), 0.02)
        self.assertGreater(len(service._pan_servo.set_angle_calls), 0)
        self.assertGreater(len(service._tilt_servo.set_angle_calls), 0)
        self.assertGreater(service._pan_servo.release_calls, 0)
        self.assertGreater(service._tilt_servo.release_calls, 0)

    def test_tracking_move_interpolates_pan_and_tilt_together(self) -> None:
        service = self.build_service()

        service._process_payload(build_payload())
        pan_start_count = len(service._pan_servo.set_angle_calls)
        tilt_start_count = len(service._tilt_servo.set_angle_calls)
        pan_release_count = service._pan_servo.release_calls
        tilt_release_count = service._tilt_servo.release_calls

        service._process_payload(build_payload(center_x=1120, center_y=140), version=2)

        pan_calls = service._pan_servo.set_angle_calls[pan_start_count:]
        tilt_calls = service._tilt_servo.set_angle_calls[tilt_start_count:]
        self.assertGreater(len(pan_calls), 1)
        self.assertEqual(len(pan_calls), len(tilt_calls))
        self.assertEqual(service._pan_servo.release_calls, pan_release_count + 1)
        self.assertEqual(service._tilt_servo.release_calls, tilt_release_count + 1)
        self.assertAlmostEqual(pan_calls[-1]["angle"], service._pan_angle)
        self.assertAlmostEqual(tilt_calls[-1]["angle"], service._tilt_angle)


if __name__ == "__main__":
    unittest.main()
