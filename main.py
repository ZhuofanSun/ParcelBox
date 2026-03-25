"""Phase 3 app entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import config
from services.access_service import AccessService
from services.button_service import ButtonService
from services.buzzer_service import BuzzerService
from services.camera_service import CameraService
from services.camera_mount_service import CameraMountService
from services.email_service import EmailNotificationService
from services.led_service import LedService
from services.locker_service import LockerService
from services.occupancy_service import OccupancyService
from services.profile_settings_service import ProfileSettingsService
from services.system_status_service import SystemStatusService
from services.vision_service import VisionService
from data.event_store import EventStore
from web.routes_cards import build_cards_router
from web.routes_control import build_control_router
from web.routes_logs import build_logs_router
from web.routes_settings import build_settings_router
from web.routes_stream import begin_stream_shutdown, build_stream_router, reset_stream_shutdown_state
from web.routes_system import build_system_router

logger = logging.getLogger(__name__)


camera_service = CameraService()
event_store = EventStore()
vision_service = VisionService(camera_service, event_store=event_store)
camera_mount_service = CameraMountService(vision_service)
vision_service.set_standby_anchor_provider(camera_mount_service.get_standby_anchor_timestamp)
camera_service.set_stream_standby_provider(vision_service.is_standby_active)
system_status_service = SystemStatusService()
profile_settings_service = ProfileSettingsService(event_store)
email_service = EmailNotificationService()
buzzer_service = BuzzerService()
button_service = ButtonService(
    snapshot_callback=camera_service.capture_snapshot,
    notification_callback=email_service.send_open_request_email,
    event_store=event_store,
)
access_service = AccessService(
    event_store=event_store,
    card_detect_callback=buzzer_service.beep_card_detected,
)
occupancy_service = OccupancyService()
locker_service = LockerService(
    access_service,
    occupancy_service,
    snapshot_callback=camera_service.capture_snapshot,
    event_store=event_store,
)
led_service = LedService(
    vision_service=vision_service,
    camera_mount_service=camera_mount_service,
    locker_service=locker_service,
    button_service=button_service,
)


def configure_logging() -> None:
    """Configure application logging for local runs."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    reset_stream_shutdown_state()
    logger.info("Application startup sequence begin")
    buzzer_service.start()
    logger.info("Buzzer service started")
    access_service.start()
    logger.info("Access service started")
    occupancy_service.start()
    logger.info("Occupancy service started")
    event_store.start()
    logger.info("Event store started")
    camera_service.start()
    logger.info("Camera service started")
    button_service.start()
    logger.info("Button service started")
    vision_service.start()
    logger.info("Vision service started")
    locker_service.start()
    logger.info("Locker service started")
    camera_mount_service.start()
    logger.info("Camera mount service started")
    led_service.start()
    logger.info("LED service started")
    try:
        yield
    finally:
        logger.info("Application shutdown sequence begin")
        await begin_stream_shutdown()
        led_service.stop()
        camera_mount_service.stop()
        locker_service.stop()
        vision_service.stop()
        button_service.stop()
        camera_service.stop()
        event_store.stop()
        occupancy_service.stop()
        access_service.stop()
        buzzer_service.stop()
        logger.info("Application shutdown sequence complete")


app = FastAPI(title="ParcelBox", lifespan=lifespan)
app.include_router(
    build_stream_router(
        camera_service,
        vision_service,
        camera_mount_service,
        button_service,
        event_store,
    )
)
app.include_router(build_control_router(locker_service))
app.include_router(build_cards_router(access_service, locker_service))
app.include_router(build_logs_router(event_store))
app.include_router(build_system_router(system_status_service))
app.include_router(build_settings_router(profile_settings_service))

frontend_dir = Path(__file__).resolve().parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def serve() -> None:
    """Run the local web server."""
    configure_logging()
    logger.info(
        "Starting ParcelBox web server on %s:%s",
        config.web.host,
        config.web.port,
    )
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
