from __future__ import annotations

import copy
import threading
import time
import unittest

from config import config
from services.button_service import ButtonService


class FakeButton:
    def __init__(self, pin: int) -> None:
        self.pin = pin
        self._press_event = threading.Event()
        self._release_event = threading.Event()
        self._release_event.set()
        self.cleaned_up = False

    def trigger_press(self) -> None:
        self._release_event.clear()
        self._press_event.set()

    def trigger_release(self) -> None:
        self._release_event.set()

    def wait_for_press(self, timeout: float = None, poll_interval: float = 0.01) -> bool:
        pressed = self._press_event.wait(timeout)
        if pressed:
            self._press_event.clear()
        return pressed

    def wait_for_release(self, timeout: float = None, poll_interval: float = 0.01) -> bool:
        return self._release_event.wait(timeout)

    def cleanup(self) -> None:
        self.cleaned_up = True


class ButtonServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        config.alert.button_press_snapshot_cooldown_seconds = 0.0

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

    def wait_for_event(self, service: ButtonService, event_id: int, timeout: float = 1.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            event = service.get_latest_event()
            if event is not None and event.get("id") == event_id:
                return event
            time.sleep(0.02)
        self.fail(f"Timed out waiting for button event {event_id}")

    def test_button_press_captures_snapshot_and_records_event(self) -> None:
        fake_button = FakeButton(27)
        snapshots: list[dict] = []
        notifications: list[dict] = []

        def capture_snapshot() -> dict:
            snapshot = {
                "filename": f"button_{len(snapshots) + 1}.jpg",
                "path": f"/tmp/button_{len(snapshots) + 1}.jpg",
            }
            snapshots.append(snapshot)
            return snapshot

        def send_notification() -> dict:
            notification = {"status": "sent"}
            notifications.append(notification)
            return notification

        service = ButtonService(
            snapshot_callback=capture_snapshot,
            notification_callback=send_notification,
            button_factory=lambda pin: fake_button,
        )
        service.start()
        self.addCleanup(service.stop)

        fake_button.trigger_press()
        fake_button.trigger_release()
        event = self.wait_for_event(service, 1)

        self.assertEqual(event["type"], "button_pressed")
        self.assertEqual(event["snapshot"]["filename"], "button_1.jpg")
        self.assertEqual(event["snapshot"]["trigger"], "button")
        self.assertEqual(event["snapshot"]["source"], "hardware_button")
        self.assertEqual(event["notification"]["status"], "sent")
        self.assertEqual(event["notification"]["trigger"], "button")
        self.assertEqual(event["notification"]["source"], "hardware_button")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(service.get_status()["latest_event"]["id"], 1)

    def test_each_press_after_release_creates_new_event(self) -> None:
        fake_button = FakeButton(27)
        capture_count = 0

        def capture_snapshot() -> dict:
            nonlocal capture_count
            capture_count += 1
            return {"filename": f"button_{capture_count}.jpg"}

        service = ButtonService(
            snapshot_callback=capture_snapshot,
            button_factory=lambda pin: fake_button,
        )
        service.start()
        self.addCleanup(service.stop)

        fake_button.trigger_press()
        fake_button.trigger_release()
        self.wait_for_event(service, 1)

        fake_button.trigger_press()
        fake_button.trigger_release()
        event = self.wait_for_event(service, 2)

        self.assertEqual(capture_count, 2)
        self.assertEqual(event["snapshot"]["filename"], "button_2.jpg")

    def test_notification_error_is_recorded_in_event(self) -> None:
        fake_button = FakeButton(27)

        def send_notification() -> dict:
            raise RuntimeError("smtp failed")

        service = ButtonService(
            snapshot_callback=lambda: {"filename": "button.jpg"},
            notification_callback=send_notification,
            button_factory=lambda pin: fake_button,
        )
        service.start()
        self.addCleanup(service.stop)

        fake_button.trigger_press()
        fake_button.trigger_release()
        event = self.wait_for_event(service, 1)

        self.assertEqual(event["notification"], None)
        self.assertEqual(event["notification_error"], "smtp failed")
        self.assertEqual(service.get_status()["last_error"], "smtp failed")

    def test_snapshot_cooldown_skips_rapid_second_capture_but_keeps_events(self) -> None:
        fake_button = FakeButton(27)
        captured: list[dict] = []
        alerts: list[dict] = []
        config.alert.button_press_snapshot_cooldown_seconds = 5.0

        def capture_snapshot() -> dict:
            snapshot = {"filename": f"button_{len(captured) + 1}.jpg"}
            captured.append(snapshot)
            return snapshot

        service = ButtonService(
            snapshot_callback=capture_snapshot,
            alert_callback=lambda event: alerts.append(event),
            button_factory=lambda pin: fake_button,
        )
        service.start()
        self.addCleanup(service.stop)

        fake_button.trigger_press()
        fake_button.trigger_release()
        first_event = self.wait_for_event(service, 1)

        fake_button.trigger_press()
        fake_button.trigger_release()
        second_event = self.wait_for_event(service, 2)

        self.assertEqual(first_event["snapshot"]["filename"], "button_1.jpg")
        self.assertEqual(len(captured), 1)
        self.assertEqual(second_event.get("snapshot"), None)
        self.assertEqual(second_event.get("snapshot_skipped_reason"), "cooldown")
        self.assertEqual(len(alerts), 2)


if __name__ == "__main__":
    unittest.main()
