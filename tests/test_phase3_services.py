from __future__ import annotations

import copy
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from config import config
from services.access_service import AccessService
from services.locker_service import LockerService
from services.occupancy_service import OccupancyService
from data.event_store import EventStore


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
        self.read_requests: list[dict] = []
        self.cleaned_up = False

    def read_uid_hex(self, timeout: float = None, poll_interval: float = 0.1) -> str | None:
        self.read_requests.append({"type": "uid", "timeout": timeout, "poll_interval": poll_interval})
        return self.uid

    def cleanup(self) -> None:
        self.cleaned_up = True


class FlakyUidReader(FakeReader):
    def __init__(self) -> None:
        super().__init__()
        self.remaining_failures = 1

    def read_uid_hex(self, timeout: float = None, poll_interval: float = 0.1) -> str | None:
        self.read_requests.append({"type": "uid", "timeout": timeout, "poll_interval": poll_interval})
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise RuntimeError("temporary scan failure")
        return super().read_uid_hex(timeout=timeout, poll_interval=poll_interval)


class SequencedUidReader(FakeReader):
    def __init__(self, sequence: list[str | None]) -> None:
        super().__init__()
        self._sequence = list(sequence)

    def read_uid_hex(self, timeout: float = None, poll_interval: float = 0.1) -> str | None:
        self.read_requests.append({"type": "uid", "timeout": timeout, "poll_interval": poll_interval})
        if self._sequence:
            next_uid = self._sequence.pop(0)
            return next_uid
        return None


class FakeLockerBridge:
    def __init__(self) -> None:
        self.processed_uids: list[dict] = []

    def process_scanned_uid(self, uid: str, *, source: str = "rfid") -> dict:
        event = {
            "type": "door_opened",
            "source": source,
            "uid": uid,
            "allowed": True,
            "reason": "granted",
        }
        self.processed_uids.append(event)
        return event


class FakeSnapshotRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self) -> dict:
        snapshot = {
            "path": f"/tmp/snapshot_{len(self.calls) + 1}.jpg",
            "saved_at": "2026-03-21T12:00:00",
        }
        self.calls.append(copy.deepcopy(snapshot))
        return snapshot


class Phase3ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        self.temp_dir = tempfile.TemporaryDirectory()
        config.storage.card_store_path = str(Path(self.temp_dir.name) / "cards.json")
        config.storage.database_url = f"sqlite:///{Path(self.temp_dir.name) / 'events.db'}"

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

    def build_access_service(self, event_store: EventStore | None = None) -> AccessService:
        return AccessService(
            reader_factory=lambda **kwargs: None,
            store_path=config.storage.card_store_path,
            event_store=event_store or self.build_event_store(),
        )

    def build_reader_access_service(
        self,
        event_store: EventStore | None = None,
        *,
        card_detect_callback=None,
    ) -> tuple[AccessService, FakeReader]:
        reader = FakeReader()
        service = AccessService(
            reader_factory=lambda **kwargs: reader,
            store_path=config.storage.card_store_path,
            event_store=event_store or self.build_event_store(),
            card_detect_callback=card_detect_callback,
        )
        service.start()
        self.addCleanup(service.stop)
        return service, reader

    def build_custom_reader_access_service(
        self,
        reader,
        event_store: EventStore | None = None,
        *,
        card_detect_callback=None,
    ) -> AccessService:
        service = AccessService(
            reader_factory=lambda **kwargs: reader,
            store_path=config.storage.card_store_path,
            event_store=event_store or self.build_event_store(),
            card_detect_callback=card_detect_callback,
        )
        service.start()
        self.addCleanup(service.stop)
        return service

    def build_occupancy_service(self) -> OccupancyService:
        service = OccupancyService(sensor_factory=FakeUltrasonicSensor)
        service.start()
        self.addCleanup(service.stop)
        return service

    def build_locker_service(
        self,
        access_service: AccessService,
        occupancy_service: OccupancyService | None = None,
        snapshot_callback=None,
        event_store: EventStore | None = None,
    ) -> LockerService:
        service = LockerService(
            access_service,
            occupancy_service,
            servo_factory=FakeServo,
            snapshot_callback=snapshot_callback,
            event_store=event_store,
        )
        service.start()
        self.addCleanup(service.stop)
        return service

    def build_event_store(self) -> EventStore:
        store = EventStore()
        store.start()
        self.addCleanup(store.stop)
        return store

    def test_enrolled_card_is_authorized(self) -> None:
        access_service = self.build_access_service()

        card = access_service.enroll_card("AB-CD", name="Courier Card")
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
        self.assertEqual(close_event["occupancy"]["state"], "empty")

    def test_ultrasonic_mid_range_is_empty(self) -> None:
        occupancy_service = self.build_occupancy_service()

        occupancy_service._sensor.next_distance_cm = 60.0
        measurement = occupancy_service.measure_once(door_state="closed")

        self.assertEqual(measurement["state"], "empty")
        self.assertEqual(measurement["reason"], "distance_above_occupied_threshold_door_closed")

    def test_ultrasonic_far_range_means_door_not_closed(self) -> None:
        occupancy_service = self.build_occupancy_service()

        occupancy_service._sensor.next_distance_cm = 140.0
        measurement = occupancy_service.measure_once(door_state="open")

        self.assertEqual(measurement["state"], "door_not_closed")
        self.assertEqual(measurement["reason"], "distance_above_occupied_threshold_door_open")

    def test_occupancy_status_uses_current_door_state_context(self) -> None:
        occupancy_service = self.build_occupancy_service()

        occupancy_service._sensor.next_distance_cm = 60.0
        occupancy_service.measure_once(door_state="closed")

        closed_status = occupancy_service.get_status(door_state="closed")
        open_status = occupancy_service.get_status(door_state="open")

        self.assertEqual(closed_status["latest_measurement"]["state"], "empty")
        self.assertEqual(open_status["latest_measurement"]["state"], "door_not_closed")

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

    def test_locker_events_are_persisted_to_sqlite_store(self) -> None:
        access_service = self.build_access_service()
        access_service.enroll_card("CAFE01", name="Tester")
        event_store = self.build_event_store()
        locker_service = self.build_locker_service(access_service, event_store=event_store)

        event = locker_service.process_scanned_uid("CAFE01", source="rfid")
        persisted_events = event_store.list_events(limit=10, category="locker")

        self.assertIsInstance(event["storage_id"], int)
        self.assertEqual(persisted_events[0]["type"], "door_opened")
        self.assertEqual(persisted_events[0]["uid"], "CAFE01")

    def test_rfid_scan_captures_snapshot_once_until_card_removed(self) -> None:
        access_service = self.build_access_service()
        access_service.enroll_card("CAFE01", name="Tester")
        snapshot_recorder = FakeSnapshotRecorder()
        locker_service = self.build_locker_service(
            access_service,
            snapshot_callback=snapshot_recorder,
        )

        first_event = locker_service.process_scanned_uid("CAFE01", source="rfid")
        duplicate_event = locker_service.process_scanned_uid("CAFE01", source="rfid")
        locker_service.note_no_card_present()
        second_event = locker_service.process_scanned_uid("CAFE01", source="rfid")

        self.assertEqual(len(snapshot_recorder.calls), 2)
        self.assertIsNotNone(first_event["snapshot"])
        self.assertIsNone(duplicate_event)
        self.assertIsNotNone(second_event["snapshot"])

    def test_duplicate_card_does_not_reopen_until_reader_sees_no_card(self) -> None:
        access_service = self.build_access_service()
        access_service.enroll_card("CAFE01", name="Tester")
        locker_service = self.build_locker_service(access_service)

        first_event = locker_service.process_scanned_uid("CAFE01", source="frontend_scan")
        close_event = locker_service.close_door(source="frontend")
        duplicate_event = locker_service.process_scanned_uid("CAFE01", source="rfid")
        status_after_duplicate = locker_service.get_status()

        locker_service.note_no_card_present()
        reopened_event = locker_service.process_scanned_uid("CAFE01", source="rfid")

        self.assertEqual(first_event["type"], "door_opened")
        self.assertEqual(close_event["type"], "door_closed")
        self.assertIsNone(duplicate_event)
        self.assertEqual(status_after_duplicate["door_state"], "closed")
        self.assertEqual(reopened_event["type"], "door_opened")

    def test_open_door_auto_closes_after_delay(self) -> None:
        access_service = self.build_access_service()
        config.door.auto_close_seconds = 0.02
        locker_service = self.build_locker_service(access_service)

        open_event = locker_service.open_door(source="frontend")
        time.sleep(0.08)
        status = locker_service.get_status()
        events = locker_service.list_events(limit=3)

        self.assertEqual(open_event["type"], "door_opened")
        self.assertEqual(status["door_state"], "closed")
        self.assertEqual(events[0]["type"], "door_closed")
        self.assertEqual(events[0]["source"], "auto_close")

    def test_unknown_card_is_denied_without_opening_door(self) -> None:
        access_service = self.build_access_service()
        locker_service = self.build_locker_service(access_service)

        event = locker_service.process_scanned_uid("DEAD55")
        status = locker_service.get_status()

        self.assertEqual(event["type"], "access_denied")
        self.assertEqual(event["reason"], "unknown_card")
        self.assertEqual(status["door_state"], "closed")
        self.assertEqual(status["current_angle"], config.door.closed_angle)

    def test_unknown_card_denial_is_persisted_for_audit(self) -> None:
        access_service = self.build_access_service()
        event_store = self.build_event_store()
        locker_service = self.build_locker_service(access_service, event_store=event_store)

        event = locker_service.process_scanned_uid("DEAD55", source="rfid")
        persisted_events = event_store.list_events(limit=10, category="locker")

        self.assertEqual(event["type"], "access_denied")
        self.assertIsInstance(event["storage_id"], int)
        self.assertEqual(persisted_events[0]["type"], "access_denied")
        self.assertEqual(persisted_events[0]["uid"], "DEAD55")
        self.assertEqual(persisted_events[0]["reason"], "unknown_card")

    def test_scan_card_returns_uid(self) -> None:
        access_service, reader = self.build_reader_access_service()

        result = access_service.scan_card()

        self.assertEqual(result["uid"], reader.uid)
        self.assertEqual(reader.read_requests[-1]["type"], "uid")

    def test_scan_card_returns_none_when_no_card_is_present(self) -> None:
        reader = SequencedUidReader([None])
        access_service = self.build_custom_reader_access_service(reader)

        result = access_service.scan_card(timeout=0.01)

        self.assertIsNone(result)

    def test_scan_card_error_does_not_break_future_scan(self) -> None:
        reader = FlakyUidReader()
        access_service = self.build_custom_reader_access_service(reader)

        with self.assertRaises(RuntimeError):
            access_service.scan_card()

        scan_result = access_service.scan_card()

        self.assertEqual(scan_result["uid"], reader.uid)

    def test_ensure_card_authorized_persists_card_record(self) -> None:
        event_store = self.build_event_store()
        access_service, reader = self.build_reader_access_service(event_store=event_store)

        card = access_service.ensure_card_authorized(reader.uid, name="courier-1")

        self.assertEqual(card["uid"], reader.uid)
        self.assertTrue(card["enabled"])
        self.assertEqual(card["name"], "courier-1")
        self.assertEqual(access_service.get_card(reader.uid)["uid"], reader.uid)
        persisted_card = event_store.get_card(reader.uid)
        self.assertEqual(persisted_card["uid"], reader.uid)
        self.assertIsNone(access_service.get_status()["store_path"])
        self.assertEqual(access_service.get_status()["store_backend"], "sqlite")

    def test_access_service_reloads_cards_from_sqlite_store(self) -> None:
        event_store = self.build_event_store()
        first_service = self.build_access_service(event_store=event_store)

        first_service.ensure_card_authorized("CAFE01", name="courier-1")

        reloaded_service = self.build_access_service(event_store=self.build_event_store())
        self.assertEqual(reloaded_service.get_card("CAFE01")["name"], "courier-1")

    def test_scan_card_flow_opens_door_for_authorized_card(self) -> None:
        access_service, reader = self.build_reader_access_service()
        access_service.ensure_card_authorized(reader.uid, name="courier-1")
        locker_bridge = FakeLockerBridge()

        result = access_service.scan_card()
        access_result = access_service.authorize_uid(result["uid"])
        door_event = None
        if access_result["allowed"]:
            door_event = locker_bridge.process_scanned_uid(result["uid"], source="frontend_scan")

        self.assertTrue(access_result["allowed"])
        self.assertEqual(door_event["type"], "door_opened")
        self.assertEqual(door_event["source"], "frontend_scan")
        self.assertEqual(locker_bridge.processed_uids[0]["uid"], reader.uid)

    def test_card_detect_callback_fires_once_until_reader_sees_no_card(self) -> None:
        beeps: list[str] = []
        reader = SequencedUidReader(["CAFE01", "CAFE01", None, "CAFE01"])
        access_service = self.build_custom_reader_access_service(
            reader,
            card_detect_callback=lambda: beeps.append("beep"),
        )

        self.assertEqual(access_service.scan_uid(), "CAFE01")
        self.assertEqual(access_service.scan_uid(), "CAFE01")
        self.assertIsNone(access_service.scan_uid())
        self.assertEqual(access_service.scan_uid(), "CAFE01")
        self.assertEqual(beeps, ["beep", "beep"])

    def test_interactive_scan_resets_card_detect_latch_before_waiting(self) -> None:
        beeps: list[str] = []
        reader = FakeReader()
        access_service = self.build_custom_reader_access_service(
            reader,
            card_detect_callback=lambda: beeps.append("beep"),
        )

        first = access_service.scan_card()
        second = access_service.scan_card()

        self.assertEqual(first["uid"], reader.uid)
        self.assertEqual(second["uid"], reader.uid)
        self.assertEqual(beeps, ["beep", "beep"])


if __name__ == "__main__":
    unittest.main()
