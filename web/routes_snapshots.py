"""Routes for viewing stored snapshot metadata and image files."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from data.event_store import EventStore


def build_snapshot_router(event_store: EventStore) -> APIRouter:
    """Create routes for stored snapshot lookup and file serving."""
    router = APIRouter()

    @router.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: int) -> dict:
        snapshot = event_store.get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        snapshot_path = event_store.resolve_snapshot_path(snapshot.get("path"))
        if snapshot_path is None or not snapshot_path.exists():
            event_store.delete_snapshots_by_paths([snapshot.get("path")])
            raise HTTPException(status_code=404, detail="Snapshot file is no longer available")

        return {
            "snapshot": {
                **snapshot,
                "file_exists": True,
                "file_url": f"/api/snapshots/{snapshot_id}/file",
            }
        }

    @router.get("/api/snapshots/{snapshot_id}/file")
    def get_snapshot_file(snapshot_id: int) -> FileResponse:
        snapshot = event_store.get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        snapshot_path = event_store.resolve_snapshot_path(snapshot.get("path"))
        if snapshot_path is None or not snapshot_path.exists():
            event_store.delete_snapshots_by_paths([snapshot.get("path")])
            raise HTTPException(status_code=404, detail="Snapshot file is no longer available")

        media_type, _ = mimetypes.guess_type(snapshot_path.name)
        return FileResponse(
            snapshot_path,
            media_type=media_type or "application/octet-stream",
            filename=snapshot_path.name,
        )

    return router
