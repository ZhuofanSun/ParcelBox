"""Routes for persisted event logs."""

from __future__ import annotations

from fastapi import APIRouter

from data.event_store import EventStore


def build_logs_router(event_store: EventStore) -> APIRouter:
    """Create event-log routes backed by the SQLite event store."""
    router = APIRouter()

    @router.get("/api/logs/status")
    def log_status() -> dict:
        return event_store.get_status()

    @router.get("/api/logs/events")
    def log_events(limit: int = 50, category: str | None = None) -> dict:
        return {
            "events": event_store.list_events(limit=limit, category=category),
        }

    return router
