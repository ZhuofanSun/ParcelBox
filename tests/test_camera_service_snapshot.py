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

    def test_capture_snapshot_prunes_oldest_50_files_after_exceeding_100(self) -> None:
        camera = FakeSnapshotCamera()
        service = CameraService(camera=camera)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            for index in range(100):
                (temp_path / f"20200101_{index:06d}.jpg").write_bytes(b"old-snapshot")

            result = service.capture_snapshot(temp_dir)

            remaining_files = sorted(path.name for path in temp_path.iterdir() if path.is_file())

            self.assertEqual(len(remaining_files), 51)
            self.assertNotIn("20200101_000000.jpg", remaining_files)
            self.assertNotIn("20200101_000049.jpg", remaining_files)
            self.assertIn("20200101_000050.jpg", remaining_files)
            self.assertIn(result["filename"], remaining_files)

    def test_capture_snapshot_reports_pruned_paths_to_callback(self) -> None:
        camera = FakeSnapshotCamera()
        service = CameraService(camera=camera)
        pruned_paths: list[Path] = []
        service.set_snapshot_prune_callback(lambda paths: pruned_paths.extend(paths))

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            for index in range(100):
                (temp_path / f"20200101_{index:06d}.jpg").write_bytes(b"old-snapshot")

            service.capture_snapshot(temp_dir)

            self.assertEqual(len(pruned_paths), 50)
            self.assertEqual(pruned_paths[0].name, "20200101_000000.jpg")
            self.assertEqual(pruned_paths[-1].name, "20200101_000049.jpg")


if __name__ == "__main__":
    unittest.main()
