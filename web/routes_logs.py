"""Routes for persisted event logs."""

from __future__ import annotations

from itertools import chain

from fastapi import APIRouter

from data.event_store import EventStore


def build_logs_router(event_store: EventStore, alert_service=None) -> APIRouter:
    """Create event-log routes backed by the SQLite event store."""
    router = APIRouter()

    @router.get("/api/logs/status")
    def log_status() -> dict:
        return event_store.get_status()

    @router.get("/api/logs/events")
    def log_events(limit: int = 50, category: str | None = None) -> dict:
        if category == "alert":
            return {
                "events": [] if alert_service is None else alert_service.list_events(limit=limit),
            }

        persisted_events = event_store.list_events(limit=limit, category=category)
        if alert_service is None or category is not None:
            return {
                "events": persisted_events,
            }

        alert_events = alert_service.list_events(limit=limit)
        merged_events = sorted(
            chain(persisted_events, alert_events),
            key=lambda event: float(event.get("timestamp") or 0.0),
            reverse=True,
        )
        return {
            "events": merged_events[: max(int(limit), 0)],
        }

    @router.get("/api/logs/tables")
    def log_tables() -> dict:
        return {
            "tables": event_store.get_table_snapshot(),
            "status": event_store.get_status(),
        }

    return router
