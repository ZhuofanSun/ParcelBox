"""Routes for RFID card enrollment and access setup."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from config import config
from services.access_service import AccessService
from services.locker_service import LockerService
from web.schemas import CardEnrollPayload, CardReadPayload, CardUpdatePayload, CardWritePayload

logger = logging.getLogger(__name__)


def _window_to_dict(window) -> dict:
    if hasattr(window, "model_dump"):
        return window.model_dump()
    return window.dict()


def build_cards_router(access_service: AccessService, locker_service: LockerService) -> APIRouter:
    """Create card-management endpoints."""
    router = APIRouter()

    def frontend_card_io_pause_seconds(timeout_seconds: float | None) -> float:
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
            locker_service.pause_rfid_polling(frontend_card_io_pause_seconds(timeout))
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

    @router.post("/api/cards/read")
    def read_card(payload: CardReadPayload) -> dict:
        logger.info("HTTP read_card request: timeout=%s", payload.scan_timeout_seconds)
        ensure_reader_available()
        timeout = payload.scan_timeout_seconds or config.rfid.enroll_scan_timeout_seconds
        locker_service.pause_rfid_polling(frontend_card_io_pause_seconds(timeout))

        try:
            result = access_service.read_card_text(
                timeout=timeout,
                start_block=payload.start_block,
                block_count=payload.block_count,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        if result is None:
            locker_service.note_no_card_present()
            logger.info("HTTP read_card waiting_for_card")
            return {
                "mode": "read",
                "status": "waiting_for_card",
                "card_io": None,
                "access_result": None,
                "door_event": None,
            }

        access_result = access_service.authorize_uid(result["uid"])
        scan_event = locker_service.process_scanned_uid(
            result["uid"],
            source="frontend_read",
            access_result=access_result,
        )
        door_event = scan_event if scan_event is not None and scan_event.get("type") == "door_opened" else None
        snapshot = None if scan_event is None else scan_event.get("snapshot")

        return {
            "card_io": result,
            "mode": "read",
            "status": "duplicate_scan_ignored" if scan_event is None else "card_detected",
            "access_result": access_result,
            "scan_event": scan_event,
            "door_event": door_event,
            "snapshot": snapshot,
        }

    @router.post("/api/cards/write")
    def write_card(payload: CardWritePayload) -> dict:
        logger.info(
            "HTTP write_card request: timeout=%s text_length=%s",
            payload.scan_timeout_seconds,
            len(payload.text),
        )
        ensure_reader_available()
        timeout = payload.scan_timeout_seconds or config.rfid.enroll_scan_timeout_seconds
        locker_service.pause_rfid_polling(frontend_card_io_pause_seconds(timeout))

        try:
            result = access_service.write_card_text(
                payload.text,
                timeout=timeout,
                start_block=payload.start_block,
                block_count=payload.block_count,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        if result is None:
            raise HTTPException(status_code=408, detail="Timed out waiting for card")

        authorized_card = access_service.ensure_card_authorized(result["uid"], name=payload.text)
        snapshot = locker_service.capture_snapshot_for_card_action(
            source="frontend_write",
            uid=result["uid"],
        )
        return {
            "card_io": result,
            "mode": "write",
            "authorized_card": authorized_card,
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
