"""Minimal Phase 2 app entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import config
from services.camera_service import CameraService
from services.vision_service import VisionService
from web.routes_stream import build_stream_router


camera_service = CameraService()
vision_service = VisionService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    camera_service.start()
    try:
        yield
    finally:
        camera_service.stop()


app = FastAPI(title="ParcelBox", lifespan=lifespan)
app.include_router(build_stream_router(camera_service, vision_service))

frontend_dir = Path(__file__).resolve().parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def serve() -> None:
    """Run the local web server."""
    uvicorn.run(
        app,
        host=config.web.host,
        port=config.web.port,
        reload=False,
    )


if __name__ == "__main__":
    serve()
