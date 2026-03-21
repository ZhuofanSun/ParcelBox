"""Phase 3 app entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import config
from services.access_service import AccessService
from services.camera_service import CameraService
from services.camera_mount_service import CameraMountService
from services.locker_service import LockerService
from services.occupancy_service import OccupancyService
from services.vision_service import VisionService
from web.routes_cards import build_cards_router
from web.routes_control import build_control_router
from web.routes_stream import begin_stream_shutdown, build_stream_router, reset_stream_shutdown_state


camera_service = CameraService()
vision_service = VisionService(camera_service)
camera_mount_service = CameraMountService(vision_service)
access_service = AccessService()
occupancy_service = OccupancyService()
locker_service = LockerService(access_service, occupancy_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    reset_stream_shutdown_state()
    access_service.start()
    occupancy_service.start()
    locker_service.start()
    camera_service.start()
    vision_service.start()
    camera_mount_service.start()
    try:
        yield
    finally:
        await begin_stream_shutdown()
        camera_mount_service.stop()
        vision_service.stop()
        camera_service.stop()
        locker_service.stop()
        occupancy_service.stop()
        access_service.stop()


app = FastAPI(title="ParcelBox", lifespan=lifespan)
app.include_router(build_stream_router(camera_service, vision_service, camera_mount_service, locker_service))
app.include_router(build_control_router(locker_service))
app.include_router(build_cards_router(access_service, locker_service))

frontend_dir = Path(__file__).resolve().parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def serve() -> None:
    """Run the local web server."""
    uvicorn.run(
        app,
        host=config.web.host,
        port=config.web.port,
        reload=False,
        access_log=config.web.access_log,
        timeout_graceful_shutdown=1,
    )


if __name__ == "__main__":
    serve()
