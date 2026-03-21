"""Routes for locker door and Phase 3 device control."""

from __future__ import annotations

from fastapi import APIRouter

from services.locker_service import LockerService
from web.schemas import LockerActionPayload


def build_control_router(locker_service: LockerService) -> APIRouter:
    """Create control endpoints for the locker workflow."""
    router = APIRouter()

    @router.get("/api/locker/status")
    def locker_status() -> dict:
        return locker_service.get_status()

    @router.get("/api/locker/events")
    def locker_events(limit: int = 30) -> dict:
        return {"events": locker_service.list_events(limit=limit)}

    @router.post("/api/locker/open")
    def locker_open(payload: LockerActionPayload) -> dict:
        return {"event": locker_service.open_door(source=payload.source)}

    @router.post("/api/locker/close")
    def locker_close(payload: LockerActionPayload) -> dict:
        return {"event": locker_service.close_door(source=payload.source)}

    return router
