"""Routes for video streaming and overlay metadata."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from config import config
from services.camera_service import CameraService
from services.vision_service import VisionService


def build_stream_router(
    camera_service: CameraService,
    vision_service: VisionService,
) -> APIRouter:
    """Create the router for stream and fake vision endpoints."""
    router = APIRouter()

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
                "jpeg_quality": config.web.jpeg_quality,
                "vision_transport": "websocket",
                "vision_ws_path": "/ws/vision",
            }
        )

    @router.get("/api/vision/boxes")
    def vision_boxes() -> JSONResponse:
        return JSONResponse(vision_service.get_boxes())

    @router.websocket("/ws/vision")
    async def vision_websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        last_seen_version = 0

        try:
            while True:
                try:
                    payload, version = await asyncio.to_thread(
                        vision_service.wait_for_latest_boxes,
                        last_seen_version,
                        5.0,
                    )
                except TimeoutError:
                    continue

                await websocket.send_json(payload)
                last_seen_version = version
        except WebSocketDisconnect:
            return

    @router.get("/api/stream.mjpg")
    def mjpeg_stream() -> StreamingResponse:
        interval = 1 / max(config.web.stream_fps, 1)

        def generate():
            last_timestamp = 0.0
            while True:
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
