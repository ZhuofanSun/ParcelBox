from __future__ import annotations

import copy
import unittest

from config import config
from services.camera_service import CameraService


class FakeStreamProfileCamera:
    def __init__(self) -> None:
        self.control_calls: list[dict] = []

    def set_controls(self, controls: dict) -> None:
        self.control_calls.append(dict(controls))


class CameraServiceStreamProfileTests(unittest.TestCase):
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

    def test_sync_stream_profile_switches_between_active_and_standby_fps(self) -> None:
        camera = FakeStreamProfileCamera()
        service = CameraService(camera=camera)
        standby_state = {"active": False}
        service.set_stream_standby_provider(lambda: standby_state["active"])
        service._started = True
        service._last_applied_stream_fps = config.web.stream_fps

        self.assertEqual(service.get_stream_fps_target(), config.web.stream_fps)

        standby_state["active"] = True
        service._sync_stream_profile()

        self.assertEqual(service.get_stream_fps_target(), config.web.standby_stream_fps)
        self.assertEqual(
            camera.control_calls[-1],
            {
                "FrameDurationLimits": (
                    int(1_000_000 / config.web.standby_stream_fps),
                    int(1_000_000 / config.web.standby_stream_fps),
                )
            },
        )

        standby_state["active"] = False
        service._sync_stream_profile()

        self.assertEqual(
            camera.control_calls[-1],
            {
                "FrameDurationLimits": (
                    int(1_000_000 / config.web.stream_fps),
                    int(1_000_000 / config.web.stream_fps),
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
