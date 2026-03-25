"""Routes for lightweight system/runtime diagnostics."""

from __future__ import annotations

from fastapi import APIRouter

from services.system_status_service import SystemStatusService


def build_system_router(system_status_service: SystemStatusService) -> APIRouter:
    """Create routes for host and process runtime metrics."""
    router = APIRouter()

    @router.get("/api/system/status")
    def system_status() -> dict:
        return system_status_service.get_status()

    return router
