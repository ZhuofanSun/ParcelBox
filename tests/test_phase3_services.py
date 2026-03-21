from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from config import config
from services.access_service import AccessService
from services.locker_service import LockerService
from services.occupancy_service import OccupancyService


class FakeServo:
    def __init__(self, pin: int, min_angle: float = 0, max_angle: float = 180, **kwargs) -> None:
        self.pin = pin
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.moves: list[dict] = []

    def move_to(self, angle: float, step: float = 1, delay: float = 0.02, release: bool = True) -> None:
        if not self.min_angle <= angle <= self.max_angle:
            raise ValueError("angle out of range")
        self.moves.append(
            {
                "angle": angle,
                "step": step,
                "delay": delay,
                "release": release,
            }
        )

    def cleanup(self) -> None:
        return None


class FakeUltrasonicSensor:
    def __init__(self, trigger_pin: int, echo_pin: int, **kwargs) -> None:
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        self.next_distance_cm = 24.0

    def measure_distance_cm(self, **kwargs) -> float | None:
        return self.next_distance_cm

    def cleanup(self) -> None:
        return None


class FakeReader:
    def __init__(self) -> None:
        self.uid = "A1B2C3D4"
        self.text = "parcel-box"
        self.read_requests: list[dict] = []
        self.write_requests: list[dict] = []
        self.cleaned_up = False

    def read_uid_hex(self, timeout: float = None, poll_interval: float = 0.1) -> str | None:
        self.read_requests.append({"type": "uid", "timeout": timeout, "poll_interval": poll_interval})
        return self.uid

    def read_text(
        self,
        start_block: int = 1,
        block_count: int = 1,
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> str:
        self.read_requests.append(
            {
                "type": "text",
                "start_block": start_block,
                "block_count": block_count,
                "timeout": timeout,
                "poll_interval": poll_interval,
            }
        )
        return self.text

    def write_text(
        self,
        text: str,
        start_block: int = 1,
        timeout: float = None,
        poll_interval: float = 0.1,
    ) -> list[int]:
        self.write_requests.append(
            {
                "text": text,
                "start_block": start_block,
                "timeout": timeout,
                "poll_interval": poll_interval,
            }
        )
        return [start_block]

    def cleanup(self) -> None:
        self.cleaned_up = True


class Phase3ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        self.temp_dir = tempfile.TemporaryDirectory()
        config.storage.card_store_path = str(Path(self.temp_dir.name) / "cards.json")

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
        self.temp_dir.cleanup()

    def build_access_service(self) -> AccessService:
        return AccessService(reader_factory=lambda **kwargs: None, store_path=config.storage.card_store_path)

    def build_reader_access_service(self) -> tuple[AccessService, FakeReader]:
        reader = FakeReader()
        service = AccessService(reader_factory=lambda **kwargs: reader, store_path=config.storage.card_store_path)
        service.start()
        self.addCleanup(service.stop)
        return service, reader

    def build_occupancy_service(self) -> OccupancyService:
        service = OccupancyService(sensor_factory=FakeUltrasonicSensor)
        service.start()
        self.addCleanup(service.stop)
        return service

    def build_locker_service(self, access_service: AccessService, occupancy_service: OccupancyService | None = None) -> LockerService:
        service = LockerService(access_service, occupancy_service, servo_factory=FakeServo)
        service.start()
        self.addCleanup(service.stop)
        return service

    def test_enrolled_card_is_authorized(self) -> None:
        access_service = self.build_access_service()

        card = access_service.enroll_card("AB-CD", name="Courier Card", user_name="Alice")
        result = access_service.authorize_uid("abcd")

        self.assertEqual(card["uid"], "ABCD")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "granted")
        self.assertEqual(result["card"]["name"], "Courier Card")

    def test_access_windows_can_deny_outside_schedule(self) -> None:
        access_service = self.build_access_service()
        access_service.enroll_card(
            "A1B2",
            access_windows=[
                {
                    "days": [0],
                    "start": "09:00",
                    "end": "18:00",
                }
            ],
        )

        allowed = access_service.authorize_uid("A1B2", when=datetime(2026, 3, 23, 10, 0))
        denied = access_service.authorize_uid("A1B2", when=datetime(2026, 3, 23, 20, 0))

        self.assertTrue(allowed["allowed"])
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["reason"], "outside_schedule")

    def test_manual_open_and_close_updates_door_state_and_occupancy(self) -> None:
        access_service = self.build_access_service()
        occupancy_service = self.build_occupancy_service()
        locker_service = self.build_locker_service(access_service, occupancy_service)

        open_event = locker_service.open_door()
        close_event = locker_service.close_door()
        status = locker_service.get_status()

        self.assertEqual(open_event["type"], "door_opened")
        self.assertEqual(close_event["type"], "door_closed")
        self.assertEqual(status["door_state"], "closed")
        self.assertEqual(status["current_angle"], config.door.closed_angle)
        self.assertEqual(close_event["occupancy"]["state"], "occupied")

    def test_authorized_rfid_scan_opens_door(self) -> None:
        access_service = self.build_access_service()
        access_service.enroll_card("CAFE01", name="Tester")
        locker_service = self.build_locker_service(access_service)

        event = locker_service.process_scanned_uid("CAFE01")
        status = locker_service.get_status()

        self.assertEqual(event["type"], "door_opened")
        self.assertEqual(event["source"], "rfid")
        self.assertEqual(event["uid"], "CAFE01")
        self.assertEqual(status["door_state"], "open")
        self.assertEqual(status["current_angle"], config.door.open_angle)

    def test_unknown_card_is_denied_without_opening_door(self) -> None:
        access_service = self.build_access_service()
        locker_service = self.build_locker_service(access_service)

        event = locker_service.process_scanned_uid("DEAD55")
        status = locker_service.get_status()

        self.assertEqual(event["type"], "access_denied")
        self.assertEqual(event["reason"], "unknown_card")
        self.assertEqual(status["door_state"], "closed")
        self.assertEqual(status["current_angle"], config.door.closed_angle)

    def test_read_card_text_uses_reader_defaults(self) -> None:
        access_service, reader = self.build_reader_access_service()

        result = access_service.read_card_text()

        self.assertEqual(result["uid"], reader.uid)
        self.assertEqual(result["text"], reader.text)
        self.assertEqual(result["start_block"], config.rfid.text_start_block)
        self.assertEqual(result["block_count"], config.rfid.text_block_count)
        self.assertEqual(reader.read_requests[-1]["type"], "text")

    def test_write_card_text_respects_capacity(self) -> None:
        access_service, reader = self.build_reader_access_service()

        result = access_service.write_card_text("hello")

        self.assertEqual(result["uid"], reader.uid)
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["blocks"], [config.rfid.text_start_block])
        self.assertEqual(reader.write_requests[-1]["text"], "hello")

        with self.assertRaises(ValueError):
            access_service.write_card_text("x" * (config.rfid.text_block_count * 16 + 1))


if __name__ == "__main__":
    unittest.main()
