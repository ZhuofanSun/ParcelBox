from __future__ import annotations

import copy
import time
import unittest

from config import config
from services.led_service import LedService


class FakeLed:
    def __init__(
        self,
        red_pin: int,
        green_pin: int,
        blue_pin: int,
        common_anode: bool = True,
        frequency: int = 1000,
        gpio_module=None,
    ) -> None:
        self.red_pin = red_pin
        self.green_pin = green_pin
        self.blue_pin = blue_pin
        self.common_anode = common_anode
        self.frequency = frequency
        self.current_rgb = (0, 0, 0)
        self.history: list[tuple[int, int, int]] = []
        self.cleaned_up = False

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        self.current_rgb = (red, green, blue)
        self.history.append(self.current_rgb)

    def off(self) -> None:
        self.set_rgb(0, 0, 0)

    def cleanup(self) -> None:
        self.cleaned_up = True


class FakeVisionService:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {"active_mode": "standby", "status": "ok"}

    def get_boxes(self) -> dict:
        return dict(self.payload)


class FakeMountService:
    def __init__(self, advice: dict | None = None) -> None:
        self.advice = advice or {"status": "waiting_for_face"}

    def get_latest_advice(self) -> dict:
        return dict(self.advice)

    def get_status(self) -> dict:
        return {"last_error": None}


class FakeLockerService:
    def __init__(self, *, door_state: str = "closed", last_access_result: dict | None = None, last_error=None) -> None:
        self.indicator_state = {
            "door_state": door_state,
            "last_access_result": last_access_result,
            "last_error": last_error,
        }

    def get_indicator_state(self) -> dict:
        return dict(self.indicator_state)


class FakeButtonService:
    def __init__(self, latest_event: dict | None = None) -> None:
        self.latest_event = latest_event

    def get_latest_event(self) -> dict | None:
        return None if self.latest_event is None else dict(self.latest_event)


class LedServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        config.led.enabled = True
        config.gpio.rgb_red_pin = 5
        config.gpio.rgb_green_pin = 6
        config.gpio.rgb_blue_pin = 26
        config.led.update_interval_seconds = 0.02
        config.led.standby_breath_cycle_seconds = 0.4
        config.led.slow_blink_cycle_seconds = 0.2
        config.led.fast_blink_cycle_seconds = 0.1
        config.led.button_pending_seconds = 1.0
        config.led.denied_flash_seconds = 1.0

    def tearDown(self) -> None:
        config.gpio = self.original_config.gpio
        config.camera = self.original_config.camera
        config.camera_mount = self.original_config.camera_mount
        config.door = self.original_config.door
        config.rfid = self.original_config.rfid
        config.buzzer = self.original_config.buzzer
        config.led = self.original_config.led
        config.ultrasonic = self.original_config.ultrasonic
        config.storage = self.original_config.storage
        config.email = self.original_config.email
        config.vision = self.original_config.vision
        config.web = self.original_config.web

    def test_standby_pattern_breathes_green(self) -> None:
        service = LedService(
            vision_service=FakeVisionService({"active_mode": "standby", "status": "ok"}),
            camera_mount_service=FakeMountService(),
            locker_service=FakeLockerService(),
            button_service=FakeButtonService(),
            led_factory=FakeLed,
        )
        service.start()
        self.addCleanup(service.stop)

        time.sleep(0.05)
        first = service.get_status()["current_rgb"]
        time.sleep(0.18)
        second = service.get_status()["current_rgb"]

        self.assertEqual(service.get_status()["pattern"], "standby_green_breathe")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        self.assertEqual(first[0], 0)
        self.assertEqual(first[2], 0)
        self.assertEqual(second[2], 0)

    def test_returning_home_does_not_force_tracking_pattern(self) -> None:
        service = LedService(
            vision_service=FakeVisionService({"active_mode": "standby", "status": "ok"}),
            camera_mount_service=FakeMountService({"status": "returning_home"}),
            locker_service=FakeLockerService(),
            button_service=FakeButtonService(),
            led_factory=FakeLed,
        )
        service.start()
        self.addCleanup(service.stop)

        time.sleep(0.05)
        status = service.get_status()

        self.assertEqual(status["pattern"], "standby_green_breathe")

    def test_open_door_pattern_is_white_solid(self) -> None:
        service = LedService(
            vision_service=FakeVisionService({"active_mode": "standby", "status": "ok"}),
            camera_mount_service=FakeMountService(),
            locker_service=FakeLockerService(door_state="open"),
            button_service=FakeButtonService(),
            led_factory=FakeLed,
        )
        service.start()
        self.addCleanup(service.stop)

        time.sleep(0.05)
        status = service.get_status()

        self.assertEqual(status["pattern"], "door_open_white_solid")
        self.assertEqual(status["current_rgb"], (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
