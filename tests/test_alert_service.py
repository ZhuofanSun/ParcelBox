from __future__ import annotations

import copy
import unittest

from config import config
from services.alert_service import AlertService


class FakeBuzzerService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def beep_unauthorized_card(self) -> bool:
        self.calls.append("unauthorized")
        return True

    def play_medium_alarm(self) -> bool:
        self.calls.append("medium")
        return True

    def play_severe_alarm(self) -> bool:
        self.calls.append("severe")
        return True

    def silence(self) -> bool:
        self.calls.append("silence")
        return True


class FakeCameraMountService:
    def __init__(self) -> None:
        self.search_active = False
        self.request_count = 0

    def request_alert_search_once(self) -> bool:
        self.request_count += 1
        if self.search_active:
            return False
        self.search_active = True
        return True

    def is_search_active(self) -> bool:
        return self.search_active


class AlertServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        config.alert.button_press_burst_threshold = 5
        config.alert.button_press_burst_window_seconds = 6.0
        config.alert.access_denied_burst_threshold = 3
        config.alert.access_denied_burst_window_seconds = 8.0

    def tearDown(self) -> None:
        config.gpio = self.original_config.gpio
        config.camera = self.original_config.camera
        config.camera_mount = self.original_config.camera_mount
        config.door = self.original_config.door
        config.rfid = self.original_config.rfid
        config.buzzer = self.original_config.buzzer
        config.alert = self.original_config.alert
        config.led = self.original_config.led
        config.ultrasonic = self.original_config.ultrasonic
        config.storage = self.original_config.storage
        config.email = self.original_config.email
        config.vision = self.original_config.vision
        config.web = self.original_config.web

    def test_single_access_denied_plays_warning_and_records_alarm(self) -> None:
        buzzer = FakeBuzzerService()
        mount = FakeCameraMountService()
        service = AlertService(buzzer, mount)

        service.handle_access_denied({"timestamp": 100.0, "uid": "CAFE01"})
        events = service.list_events(limit=5)

        self.assertEqual(buzzer.calls, ["unauthorized"])
        self.assertEqual(mount.request_count, 1)
        self.assertEqual(events[0]["type"], "unauthorized_card_alarm")
        self.assertEqual(events[0]["uid"], "CAFE01")

    def test_repeated_access_denied_escalates_to_severe_once(self) -> None:
        buzzer = FakeBuzzerService()
        mount = FakeCameraMountService()
        service = AlertService(buzzer, mount)

        service.handle_access_denied({"timestamp": 100.0, "uid": "A"})
        mount.search_active = False
        service.handle_access_denied({"timestamp": 101.0, "uid": "B"})
        mount.search_active = False
        service.handle_access_denied({"timestamp": 102.0, "uid": "C"})
        events = service.list_events(limit=10)

        self.assertIn("severe", buzzer.calls)
        self.assertTrue(any(event["type"] == "access_denied_burst_alarm" for event in events))

    def test_button_burst_alarm_waits_for_search_completion_to_reset(self) -> None:
        buzzer = FakeBuzzerService()
        mount = FakeCameraMountService()
        service = AlertService(buzzer, mount)

        for offset in range(5):
            service.handle_button_pressed({"timestamp": 100.0 + offset * 0.2})

        self.assertIn("medium", buzzer.calls)
        self.assertTrue(mount.search_active)

        for offset in range(5, 9):
            service.handle_button_pressed({"timestamp": 100.0 + offset * 0.2})
        medium_count_before_reset = buzzer.calls.count("medium")

        service.on_alert_search_completed()
        mount.search_active = False

        for offset in range(10, 15):
            service.handle_button_pressed({"timestamp": 110.0 + offset * 0.2})

        self.assertEqual(medium_count_before_reset, 1)
        self.assertEqual(buzzer.calls.count("medium"), 2)


if __name__ == "__main__":
    unittest.main()
