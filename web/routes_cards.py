"""Routes for RFID card enrollment and access setup."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from config import config
from services.access_service import AccessService
from services.locker_service import LockerService
from web.schemas import CardEnrollPayload, CardUpdatePayload

logger = logging.getLogger(__name__)


def _window_to_dict(window) -> dict:
    if hasattr(window, "model_dump"):
        return window.model_dump()
    return window.dict()


def build_cards_router(access_service: AccessService, locker_service: LockerService) -> APIRouter:
    """Create card-management endpoints."""
    router = APIRouter()

    def frontend_card_enroll_pause_seconds(timeout_seconds: float | None) -> float:
        timeout = 0.0 if timeout_seconds is None else max(float(timeout_seconds), 0.0)
        settle = max(config.rfid.same_card_cooldown_seconds, 0.5)
        return timeout + settle

    def ensure_reader_available() -> None:
        if not access_service.get_status()["reader_enabled"]:
            raise HTTPException(status_code=503, detail="RFID reader is unavailable")

    @router.get("/api/cards")
    def list_cards() -> dict:
        logger.info("HTTP list_cards request")
        return {
            "cards": access_service.list_cards(),
            "status": access_service.get_status(),
        }

    @router.get("/api/cards/{uid}")
    def get_card(uid: str) -> dict:
        logger.info("HTTP get_card request: uid=%s", uid)
        card = access_service.get_card(uid)
        if card is None:
            raise HTTPException(status_code=404, detail="Card not found")
        return {"card": card}

    @router.post("/api/cards/enroll")
    def enroll_card(payload: CardEnrollPayload) -> dict:
        logger.info("HTTP enroll_card request: provided_uid=%s overwrite=%s", payload.uid, payload.overwrite)
        uid = payload.uid
        snapshot = None
        if uid is None:
            ensure_reader_available()
            timeout = payload.scan_timeout_seconds or config.rfid.enroll_scan_timeout_seconds
            locker_service.pause_rfid_polling(frontend_card_enroll_pause_seconds(timeout))
            access_service.reset_card_detect_latch()
            uid = access_service.scan_uid(timeout=timeout)
            if uid is None:
                raise HTTPException(status_code=408, detail="Timed out waiting for card")
            snapshot = locker_service.capture_snapshot_for_card_action(
                source="frontend_enroll",
                uid=uid,
            )

        try:
            card = access_service.enroll_card(
                uid,
                name=payload.name,
                enabled=payload.enabled,
                overwrite=payload.overwrite,
                access_windows=[_window_to_dict(window) for window in payload.access_windows],
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        return {
            "card": card,
            "snapshot": snapshot,
        }

    @router.patch("/api/cards/{uid}")
    def update_card(uid: str, payload: CardUpdatePayload) -> dict:
        logger.info("HTTP update_card request: uid=%s", uid)
        try:
            card = access_service.update_card(
                uid,
                name=payload.name,
                enabled=payload.enabled,
                access_windows=(
                    None
                    if payload.access_windows is None
                    else [_window_to_dict(window) for window in payload.access_windows]
                ),
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        return {"card": card}

    return router
