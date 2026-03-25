from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from config import config
from data.event_store import EventStore

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web.routes_snapshots import build_snapshot_router
except ModuleNotFoundError:  # pragma: no cover - depends on local env
    FastAPI = None
    TestClient = None
    build_snapshot_router = None


@unittest.skipUnless(FastAPI is not None and TestClient is not None, "fastapi is not installed in this environment")
class SnapshotRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "events.db"
        config.storage.database_url = f"sqlite:///{self.db_path}"

        self.store = EventStore()
        self.store.start()
        self.addCleanup(self.store.stop)

        app = FastAPI()
        app.include_router(build_snapshot_router(self.store))
        self.client = TestClient(app)

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

    def record_snapshot(self, filename: str) -> tuple[dict, Path]:
        path = Path(self.temp_dir.name) / filename
        path.write_bytes(b"snapshot-bytes")
        snapshot = self.store.record_snapshot(
            {
                "path": str(path),
                "filename": filename,
                "saved_at": "2026-03-25T05:00:00",
                "trigger": "manual",
            },
            default_trigger="manual",
            default_timestamp=1774429200.0,
        )
        return snapshot, path

    def test_get_snapshot_metadata_returns_file_url(self) -> None:
        snapshot, _ = self.record_snapshot("viewer.jpg")

        response = self.client.get(f"/api/snapshots/{snapshot['storage_id']}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["snapshot"]
        self.assertEqual(payload["id"], snapshot["storage_id"])
        self.assertEqual(payload["filename"], "viewer.jpg")
        self.assertTrue(payload["file_exists"])
        self.assertEqual(payload["file_url"], f"/api/snapshots/{snapshot['storage_id']}/file")

    def test_get_snapshot_file_returns_image_bytes(self) -> None:
        snapshot, _ = self.record_snapshot("viewer.jpg")

        response = self.client.get(f"/api/snapshots/{snapshot['storage_id']}/file")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"snapshot-bytes")
        self.assertEqual(response.headers["content-type"], "image/jpeg")

    def test_missing_snapshot_file_returns_404_and_cleans_stale_row(self) -> None:
        snapshot, path = self.record_snapshot("stale.jpg")
        path.unlink()

        response = self.client.get(f"/api/snapshots/{snapshot['storage_id']}/file")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.store.get_table_snapshot()["snapshot"], [])


if __name__ == "__main__":
    unittest.main()
