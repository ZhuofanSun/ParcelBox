"""Routes for video streaming and overlay metadata."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from services.camera_service import CameraService
from services.camera_mount_service import CameraMountService
from services.button_service import ButtonService
from services.vision_service import VisionService
from data.event_store import EventStore

logger = logging.getLogger(__name__)


ACTIVE_VISION_WEBSOCKETS: set[WebSocket] = set()
STREAM_SHUTDOWN_EVENT = asyncio.Event()


def reset_stream_shutdown_state() -> None:
    """Clear shutdown flags when the app starts."""
    STREAM_SHUTDOWN_EVENT.clear()


async def begin_stream_shutdown() -> None:
    """Signal routes to stop streaming and close active vision websockets."""
    STREAM_SHUTDOWN_EVENT.set()

    if not ACTIVE_VISION_WEBSOCKETS:
        return

    closing_tasks = []
    for websocket in list(ACTIVE_VISION_WEBSOCKETS):
        closing_tasks.append(websocket.close(code=1001, reason="Server shutting down"))

    with suppress(Exception):
        await asyncio.gather(*closing_tasks, return_exceptions=True)


def build_stream_router(
    camera_service: CameraService,
    vision_service: VisionService,
    camera_mount_service: CameraMountService | None = None,
    button_service: ButtonService | None = None,
    event_store: EventStore | None = None,
) -> APIRouter:
    """Create the router for stream and vision endpoints."""
    router = APIRouter()

    def enrich_payload(payload: dict) -> dict:
        enriched_payload = dict(payload)
        if camera_mount_service is not None:
            enriched_payload = camera_mount_service.enrich_payload(enriched_payload)
        if button_service is not None:
            enriched_payload["button_event"] = button_service.get_latest_event()
        return enriched_payload

    @router.get("/api/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @router.post("/api/camera/snapshot")
    def capture_snapshot() -> JSONResponse:
        logger.info("HTTP snapshot request received from frontend")
        try:
            payload = camera_service.capture_snapshot()
        except RuntimeError as error:
            logger.warning("HTTP snapshot request failed: %s", error)
            return JSONResponse({"detail": str(error)}, status_code=503)

        if isinstance(payload, dict):
            payload.setdefault("trigger", "manual")
            payload.setdefault("source", "frontend_manual")

        event = None
        if event_store is not None:
            stored_snapshot = event_store.record_snapshot(
                payload,
                default_trigger="manual",
                default_timestamp=time.time(),
            )
            event = {
                "type": "manual_snapshot_captured",
                "source": "frontend_manual",
                "timestamp": time.time(),
                "snapshot": stored_snapshot,
            }
            if stored_snapshot is not None and stored_snapshot.get("storage_id") is not None:
                event["storage_id"] = int(stored_snapshot["storage_id"])
                event["storage_category"] = "snapshot"

        logger.info(
            "HTTP snapshot saved: filename=%s storage_id=%s",
            None if payload is None else payload.get("filename"),
            None if event is None else event.get("storage_id"),
        )
        return JSONResponse({"snapshot": payload, "event": event})

    @router.websocket("/ws/vision")
    async def vision_websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        last_seen_version = 0
        ACTIVE_VISION_WEBSOCKETS.add(websocket)
        logger.info("Vision websocket connected from %s", websocket.client)

        try:
            while not STREAM_SHUTDOWN_EVENT.is_set():
                try:
                    payload, version = await asyncio.to_thread(
                        vision_service.wait_for_latest_boxes,
                        last_seen_version,
                        0.5,
                    )
                except TimeoutError:
                    continue

                await websocket.send_json(enrich_payload(payload))
                last_seen_version = version
        except WebSocketDisconnect:
            logger.info("Vision websocket disconnected from %s", websocket.client)
            return
        except asyncio.CancelledError:
            logger.info("Vision websocket cancelled for %s", websocket.client)
            return
        finally:
            ACTIVE_VISION_WEBSOCKETS.discard(websocket)

    @router.get("/api/stream.mjpg")
    def mjpeg_stream() -> StreamingResponse:
        def generate():
            logger.info("MJPEG stream opened")
            last_timestamp = 0.0
            try:
                while not STREAM_SHUTDOWN_EVENT.is_set():
                    try:
                        frame_bytes, timestamp = camera_service.wait_for_latest_stream_jpeg()
                    except RuntimeError:
                        time.sleep(0.1)
                        continue

                    if timestamp != last_timestamp:
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                        )
                        last_timestamp = timestamp

                    interval = 1 / max(camera_service.get_stream_fps_target(), 1)
                    time.sleep(interval)
            finally:
                logger.info("MJPEG stream closed")

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Accel-Buffering": "no",
            },
        )

    return router
