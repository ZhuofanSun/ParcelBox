from __future__ import annotations

import copy
import time
import unittest

from config import config
from services.buzzer_service import BuzzerService


class FakeBuzzer:
    def __init__(self, pin: int, active_high: bool = True, gpio_module=None) -> None:
        self.pin = pin
        self.calls: list[dict] = []
        self.cleaned_up = False

    def beep(self, duration: float = 0.2, repeat: int = 1, interval: float = 0.1) -> None:
        self.calls.append(
            {
                "duration": duration,
                "repeat": repeat,
                "interval": interval,
            }
        )

    def cleanup(self) -> None:
        self.cleaned_up = True


class BuzzerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        config.buzzer.enabled = True
        config.gpio.buzzer_pin = 25
        config.buzzer.card_detect_beep_duration = 0.05
        config.buzzer.card_detect_beep_repeat = 1
        config.buzzer.card_detect_beep_interval = 0.0

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

    def test_card_detect_beep_is_enqueued_and_played(self) -> None:
        service = BuzzerService(buzzer_factory=FakeBuzzer)
        service.start()
        self.addCleanup(service.stop)

        played = service.beep_card_detected()
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if service._buzzer is not None and service._buzzer.calls:
                break
            time.sleep(0.02)

        self.assertTrue(played)
        self.assertEqual(service._buzzer.calls[0]["duration"], 0.05)
        self.assertEqual(service._buzzer.calls[0]["repeat"], 1)


if __name__ == "__main__":
    unittest.main()
