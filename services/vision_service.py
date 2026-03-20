"""Temporary Phase 2 fake vision service."""

from __future__ import annotations

import math
import time

from config import config


class VisionService:
    """Fake vision output used to validate frontend overlays."""

    def get_boxes(self) -> dict:
        """Return fake detection boxes in stream coordinates."""
        now = time.time()
        stream_width, stream_height = config.camera.stream_size

        box_width = int(stream_width * 0.18)
        box_height = int(stream_height * 0.38)
        center_x = int(stream_width * 0.5 + math.sin(now * 0.8) * stream_width * 0.22)
        center_y = int(stream_height * 0.5 + math.cos(now * 0.6) * stream_height * 0.12)

        x1 = max(0, center_x - box_width // 2)
        y1 = max(0, center_y - box_height // 2)
        x2 = min(stream_width - 1, x1 + box_width)
        y2 = min(stream_height - 1, y1 + box_height)

        return {
            "mode": "fake_person",
            "frame_size": {
                "width": stream_width,
                "height": stream_height,
            },
            "boxes": [
                {
                    "id": "fake-person-1",
                    "label": "person",
                    "score": 0.99,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            ],
            "timestamp": now,
        }
