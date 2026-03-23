from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from config import config
from data.event_store import EventStore


class EventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "events.db"
        config.storage.database_url = f"sqlite:///{self.db_path}"

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
        self.temp_dir.cleanup()

    def build_store(self) -> EventStore:
        store = EventStore()
        store.start()
        self.addCleanup(store.stop)
        return store

    def test_record_access_attempt_and_open_session_persist_snapshot(self) -> None:
        store = self.build_store()

        attempt = store.record_access_attempt(
            card_uid="CAFE01",
            source="rfid",
            allowed=True,
            reason="granted",
            checked_at=1774128429.0,
            snapshot={
                "path": "/tmp/door_opened.jpg",
                "filename": "door_opened.jpg",
                "saved_at": "2026-03-21T12:00:00",
                "trigger": "rfid",
            },
        )
        session = store.open_door_session(
            access_attempt_id=attempt["id"],
            open_source="rfid",
            opened_at=1774128429.0,
        )

        self.assertIsInstance(attempt["id"], int)
        self.assertIsInstance(session["id"], int)
        self.assertEqual(attempt["snapshot"]["filename"], "door_opened.jpg")

        events = store.list_events(limit=10, category="locker")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "door_opened")
        self.assertEqual(events[0]["snapshot"]["filename"], "door_opened.jpg")

        status = store.get_status()
        self.assertEqual(status["access_attempt_count"], 1)
        self.assertEqual(status["door_session_count"], 1)
        self.assertEqual(status["snapshot_count"], 1)

    def test_close_door_session_updates_occupancy(self) -> None:
        store = self.build_store()
        session = store.open_door_session(open_source="frontend", opened_at=1774128429.0)

        closed = store.close_door_session(
            close_source="frontend",
            closed_at=1774128430.0,
            occupancy={
                "state": "empty",
                "distance_cm": 42.0,
                "measured_at": 1774128431.0,
            },
        )

        self.assertEqual(closed["id"], session["id"])
        events = store.list_events(limit=10, category="locker")
        self.assertEqual(events[0]["type"], "door_closed")
        self.assertEqual(events[0]["occupancy"]["distance_cm"], 42.0)

    def test_record_button_request_persists_snapshot_and_notification(self) -> None:
        store = self.build_store()

        request = store.record_button_request(
            pressed_at=1774128429.0,
            notification={"status": "sent", "timestamp": 1774128430.0},
            snapshot={
                "path": "/tmp/button.jpg",
                "filename": "button.jpg",
                "saved_at": "2026-03-21T12:00:00",
                "trigger": "button",
            },
        )

        self.assertIsInstance(request["id"], int)
        self.assertEqual(request["snapshot"]["filename"], "button.jpg")
        events = store.list_events(limit=10, category="button")
        self.assertEqual(events[0]["type"], "button_pressed")
        self.assertEqual(events[0]["notification"]["status"], "sent")
        self.assertEqual(events[0]["snapshot"]["filename"], "button.jpg")

    def test_upsert_card_persists_rfid_cards_in_sqlite(self) -> None:
        store = self.build_store()

        stored_card = store.upsert_card(
            {
                "uid": "CAFE01",
                "name": "Courier Card",
                "enabled": True,
                "access_windows": [{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "18:00"}],
                "created_at": 1774128429.0,
                "updated_at": 1774128429.0,
            }
        )

        self.assertEqual(stored_card["uid"], "CAFE01")
        self.assertEqual(store.get_card("CAFE01")["name"], "Courier Card")
        self.assertEqual(store.list_cards()[0]["access_windows"][0]["start"], "09:00")
        self.assertEqual(store.get_status()["card_count"], 1)

    def test_get_table_snapshot_returns_all_business_tables(self) -> None:
        store = self.build_store()

        card = store.upsert_card(
            {
                "uid": "CAFE01",
                "name": "Courier Card",
                "enabled": True,
                "access_windows": [],
                "created_at": 1774128429.0,
                "updated_at": 1774128429.0,
            }
        )
        attempt = store.record_access_attempt(
            card_uid=card["uid"],
            source="rfid",
            allowed=True,
            reason="granted",
            checked_at=1774128429.0,
        )
        store.open_door_session(
            access_attempt_id=attempt["id"],
            open_source="rfid",
            opened_at=1774128429.0,
        )
        store.record_button_request(
            pressed_at=1774128430.0,
            notification={"status": "duplicate_filtered"},
            snapshot={
                "path": "/tmp/button.jpg",
                "filename": "button.jpg",
                "saved_at": "2026-03-21T12:00:00",
                "trigger": "button",
            },
        )
        store.record_snapshot(
            {
                "path": "/tmp/manual.jpg",
                "filename": "manual.jpg",
                "saved_at": "2026-03-21T12:00:01",
                "trigger": "manual",
            },
            default_trigger="manual",
            default_timestamp=1774128431.0,
        )

        snapshot = store.get_table_snapshot()

        self.assertEqual(snapshot["rfid_card"][0]["uid"], "CAFE01")
        self.assertEqual(snapshot["access_attempt"][0]["card_uid"], "CAFE01")
        self.assertEqual(snapshot["door_session"][0]["access_attempt_id"], attempt["id"])
        self.assertTrue(snapshot["button_request"][0]["email_duplicated"])
        self.assertEqual(snapshot["snapshot"][0]["trigger"], "manual")


if __name__ == "__main__":
    unittest.main()
