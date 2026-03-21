from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from services.camera_service import CameraService


class FakeSnapshotCamera:
    def __init__(self) -> None:
        self.saved_paths: list[str] = []

    def capture_file(self, path: str) -> None:
        self.saved_paths.append(path)
        Path(path).write_bytes(b"snapshot-bytes")


class CameraServiceSnapshotTests(unittest.TestCase):
    def test_capture_snapshot_saves_jpeg_with_timestamp_name(self) -> None:
        camera = FakeSnapshotCamera()
        service = CameraService(camera=camera)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = service.capture_snapshot(temp_dir)

            output_path = Path(result["path"])
            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.read_bytes(), b"snapshot-bytes")
            self.assertEqual(output_path.parent, Path(temp_dir))
            self.assertRegex(result["filename"], r"^\d{8}_\d{6}(?:_\d+)?\.jpg$")
            self.assertEqual(camera.saved_paths, [str(output_path)])
            self.assertTrue(result["saved_at"])


if __name__ == "__main__":
    unittest.main()
