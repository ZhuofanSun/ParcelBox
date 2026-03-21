"""Routes for video streaming and overlay metadata."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from config import config
from services.camera_service import CameraService
from services.camera_mount_service import CameraMountService
from services.button_service import ButtonService
from services.locker_service import LockerService
from services.vision_service import VisionService


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
    locker_service: LockerService | None = None,
    button_service: ButtonService | None = None,
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

    @router.get("/api/stream/meta")
    def stream_meta() -> JSONResponse:
        return JSONResponse(
            {
                "stream_size": {
                    "width": camera_service.stream_size[0],
                    "height": camera_service.stream_size[1],
                },
                "detection_size": {
                    "width": camera_service.detection_size[0],
                    "height": camera_service.detection_size[1],
                },
                "stream_fps": config.web.stream_fps,
                "detection_fps": config.vision.detection_fps,
                "vision_backend": config.vision.backend,
                "vision_mode": config.vision.mode,
                "jpeg_quality": config.web.jpeg_quality,
                "vision_transport": "websocket",
                "vision_ws_path": "/ws/vision",
                "camera_mount_status": (
                    camera_mount_service.get_status()
                    if camera_mount_service is not None
                    else None
                ),
                "locker_status": (
                    locker_service.get_status()
                    if locker_service is not None
                    else None
                ),
                "button_status": (
                    button_service.get_status()
                    if button_service is not None
                    else None
                ),
            }
        )

    @router.get("/api/vision/boxes")
    def vision_boxes() -> JSONResponse:
        return JSONResponse(enrich_payload(vision_service.get_boxes()))

    @router.post("/api/camera/snapshot")
    def capture_snapshot() -> JSONResponse:
        try:
            payload = camera_service.capture_snapshot()
        except RuntimeError as error:
            return JSONResponse({"detail": str(error)}, status_code=503)

        return JSONResponse({"snapshot": payload})

    @router.websocket("/ws/vision")
    async def vision_websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        last_seen_version = 0
        ACTIVE_VISION_WEBSOCKETS.add(websocket)

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
            return
        except asyncio.CancelledError:
            return
        finally:
            ACTIVE_VISION_WEBSOCKETS.discard(websocket)

    @router.get("/api/stream.mjpg")
    def mjpeg_stream() -> StreamingResponse:
        interval = 1 / max(config.web.stream_fps, 1)

        def generate():
            last_timestamp = 0.0
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

                time.sleep(interval)

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return router
