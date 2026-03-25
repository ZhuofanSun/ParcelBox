from __future__ import annotations

import copy
import os
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

    def build_snapshot_payload(self, filename: str, *, trigger: str, saved_at: str) -> dict:
        path = Path(self.temp_dir.name) / filename
        path.write_bytes(b"snapshot")
        return {
            "path": str(path),
            "filename": filename,
            "saved_at": saved_at,
            "trigger": trigger,
        }

    def test_record_access_attempt_and_open_session_persist_snapshot(self) -> None:
        store = self.build_store()

        attempt = store.record_access_attempt(
            card_uid="CAFE01",
            source="rfid",
            allowed=True,
            reason="granted",
            checked_at=1774128429.0,
            snapshot=self.build_snapshot_payload(
                "door_opened.jpg",
                trigger="rfid",
                saved_at="2026-03-21T12:00:00",
            ),
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
            snapshot=self.build_snapshot_payload(
                "button.jpg",
                trigger="button",
                saved_at="2026-03-21T12:00:00",
            ),
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
            snapshot=self.build_snapshot_payload(
                "button.jpg",
                trigger="button",
                saved_at="2026-03-21T12:00:00",
            ),
        )
        store.record_snapshot(
            self.build_snapshot_payload(
                "manual.jpg",
                trigger="manual",
                saved_at="2026-03-21T12:00:01",
            ),
            default_trigger="manual",
            default_timestamp=1774128431.0,
        )

        snapshot = store.get_table_snapshot()

        self.assertEqual(snapshot["rfid_card"][0]["uid"], "CAFE01")
        self.assertEqual(snapshot["access_attempt"][0]["card_uid"], "CAFE01")
        self.assertEqual(snapshot["door_session"][0]["access_attempt_id"], attempt["id"])
        self.assertTrue(snapshot["button_request"][0]["email_duplicated"])
        self.assertEqual(snapshot["snapshot"][0]["trigger"], "manual")
        self.assertEqual(snapshot["email_subscription_scheme"], [])
        self.assertEqual(snapshot["email_subscription_recipient"], [])

    def test_email_subscription_scheme_persists_recipients_and_single_enabled_state(self) -> None:
        store = self.build_store()

        first = store.create_email_subscription_scheme(
            name="Primary",
            enabled=True,
            username="primary@example.com",
            password="secret-1",
            from_address="parcelbox@example.com",
            recipients=["frontdesk@example.com"],
        )
        second = store.create_email_subscription_scheme(
            name="Backup",
            enabled=False,
            username="backup@example.com",
            password="secret-2",
            from_address="backup@example.com",
            recipients=["ops@example.com", "admin@example.com"],
        )

        self.assertEqual(store.get_active_email_subscription_scheme()["id"], first["id"])
        self.assertEqual(len(store.list_email_subscription_schemes()), 2)

        updated = store.update_email_subscription_scheme(
            second["id"],
            enabled=True,
            recipients=["frontdesk@example.com", "support@example.com"],
        )

        self.assertTrue(updated["enabled"])
        self.assertEqual(store.get_active_email_subscription_scheme()["id"], second["id"])
        self.assertEqual(
            [entry["email"] for entry in store.get_email_subscription_scheme(second["id"])["recipients"]],
            ["frontdesk@example.com", "support@example.com"],
        )
        self.assertFalse(store.get_email_subscription_scheme(first["id"])["enabled"])
        snapshot = store.get_table_snapshot()
        self.assertEqual(snapshot["email_subscription_scheme"][0]["name"], "Backup")
        self.assertEqual(
            {entry["email"] for entry in snapshot["email_subscription_recipient"]},
            {"frontdesk@example.com", "support@example.com"},
        )

    def test_start_reconciles_snapshot_rows_when_files_are_missing(self) -> None:
        existing_path = Path(self.temp_dir.name) / "existing.jpg"
        stale_path = Path(self.temp_dir.name) / "stale.jpg"
        existing_path.write_bytes(b"existing")
        stale_path.write_bytes(b"stale")

        first_store = self.build_store()
        first_store.record_snapshot(
            {
                "path": str(existing_path),
                "filename": existing_path.name,
                "saved_at": "2026-03-25T04:00:00",
                "trigger": "manual",
            },
            default_trigger="manual",
            default_timestamp=1774425600.0,
        )
        first_store.record_snapshot(
            {
                "path": str(stale_path),
                "filename": stale_path.name,
                "saved_at": "2026-03-25T04:00:01",
                "trigger": "manual",
            },
            default_trigger="manual",
            default_timestamp=1774425601.0,
        )
        first_store.stop()

        stale_path.unlink()

        second_store = EventStore()
        second_store.start()
        self.addCleanup(second_store.stop)

        snapshot_rows = second_store.get_table_snapshot()["snapshot"]
        self.assertEqual([row["filename"] for row in snapshot_rows], [existing_path.name])

    def test_delete_snapshots_by_paths_removes_matching_snapshot_rows(self) -> None:
        store = self.build_store()
        first_path = Path(self.temp_dir.name) / "delete_me.jpg"
        second_path = Path(self.temp_dir.name) / "keep_me.jpg"
        first_path.write_bytes(b"first")
        second_path.write_bytes(b"second")

        store.record_snapshot(
            {
                "path": str(first_path),
                "filename": first_path.name,
                "saved_at": "2026-03-25T04:10:00",
                "trigger": "manual",
            },
            default_trigger="manual",
            default_timestamp=1774426200.0,
        )
        store.record_snapshot(
            {
                "path": str(second_path),
                "filename": second_path.name,
                "saved_at": "2026-03-25T04:10:01",
                "trigger": "manual",
            },
            default_trigger="manual",
            default_timestamp=1774426201.0,
        )

        deleted = store.delete_snapshots_by_paths([first_path, Path(os.path.relpath(second_path, Path.cwd()))])

        self.assertEqual(deleted, 2)
        self.assertEqual(store.get_table_snapshot()["snapshot"], [])

    def test_get_snapshot_returns_detail_record(self) -> None:
        store = self.build_store()
        snapshot = store.record_snapshot(
            self.build_snapshot_payload(
                "detail.jpg",
                trigger="manual",
                saved_at="2026-03-25T04:15:00",
            ),
            default_trigger="manual",
            default_timestamp=1774426500.0,
        )

        stored_snapshot = store.get_snapshot(snapshot["storage_id"])

        self.assertIsNotNone(stored_snapshot)
        self.assertEqual(stored_snapshot["id"], snapshot["storage_id"])
        self.assertEqual(stored_snapshot["storage_id"], snapshot["storage_id"])
        self.assertEqual(stored_snapshot["filename"], "detail.jpg")
        self.assertEqual(stored_snapshot["access_attempt_id"], None)
        self.assertEqual(stored_snapshot["button_request_id"], None)


if __name__ == "__main__":
    unittest.main()
