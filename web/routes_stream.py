"""Routes for video streaming and overlay metadata."""

from __future__ import annotations

import time

from fastapi import APIRouter
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
                "boxes_fps": config.web.boxes_fps,
            }
        )

    @router.get("/api/vision/boxes")
    def vision_boxes() -> JSONResponse:
        return JSONResponse(vision_service.get_boxes())

    @router.get("/api/stream.mjpg")
    def mjpeg_stream() -> StreamingResponse:
        interval = 1 / max(config.web.stream_fps, 1)

        def generate():
            while True:
                frame_bytes = camera_service.get_stream_frame_jpeg()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
                time.sleep(interval)

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return router
