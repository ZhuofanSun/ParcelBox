from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from config import config
from storage.event_store import EventStore


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

    def test_record_event_persists_snapshot_and_payload(self) -> None:
        store = self.build_store()

        stored_event = store.record_event(
            "locker",
            {
                "type": "door_opened",
                "source": "rfid",
                "uid": "CAFE01",
                "allowed": True,
                "reason": "granted",
                "timestamp": 1774128429.0,
                "snapshot": {
                    "path": "/tmp/door_opened.jpg",
                    "filename": "door_opened.jpg",
                    "saved_at": "2026-03-21T12:00:00",
                    "trigger": "rfid",
                    "source": "rfid",
                },
            },
        )

        self.assertIsInstance(stored_event["storage_id"], int)
        self.assertEqual(stored_event["storage_category"], "locker")
        self.assertIsInstance(stored_event["snapshot"]["storage_id"], int)

        events = store.list_events(limit=10, category="locker")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "door_opened")
        self.assertEqual(events[0]["snapshot"]["filename"], "door_opened.jpg")

        status = store.get_status()
        self.assertEqual(status["event_count"], 1)
        self.assertEqual(status["snapshot_count"], 1)

    def test_update_event_rewrites_payload(self) -> None:
        store = self.build_store()
        stored_event = store.record_event(
            "locker",
            {
                "type": "door_closed",
                "source": "frontend",
                "timestamp": 1774128430.0,
            },
        )
        stored_event["occupancy"] = {
            "state": "empty",
            "distance_cm": 42.0,
        }

        updated_event = store.update_event(stored_event)

        self.assertEqual(updated_event["occupancy"]["state"], "empty")
        events = store.list_events(limit=10, category="locker")
        self.assertEqual(events[0]["occupancy"]["distance_cm"], 42.0)

    def test_upsert_card_persists_rfid_cards_in_sqlite(self) -> None:
        store = self.build_store()

        stored_card = store.upsert_card(
            {
                "uid": "CAFE01",
                "name": "Courier Card",
                "user_name": "Alice",
                "enabled": True,
                "access_windows": [{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "18:00"}],
                "created_at": 1774128429.0,
                "updated_at": 1774128429.0,
            }
        )

        self.assertEqual(stored_card["uid"], "CAFE01")
        self.assertEqual(store.get_card("CAFE01")["name"], "Courier Card")
        self.assertEqual(store.list_cards()[0]["user_name"], "Alice")
        self.assertEqual(store.get_status()["card_count"], 1)


if __name__ == "__main__":
    unittest.main()
