"""Locker door workflow orchestration."""

from __future__ import annotations

import copy
import threading
import time

from config import config
from drivers.servo import Servo
from services.access_service import AccessService
from services.occupancy_service import OccupancyService


class LockerService:
    """Coordinate RFID authorization, door servo moves, and occupancy checks."""

    def __init__(
        self,
        access_service: AccessService,
        occupancy_service: OccupancyService | None = None,
        servo_factory=Servo,
    ) -> None:
        self._access_service = access_service
        self._occupancy_service = occupancy_service
        self._servo_factory = servo_factory
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._started = False
        self._door_servo = None
        self._door_servo_enabled = False
        self._door_angle: float | None = None
        self._door_state = "unknown"
        self._last_error: str | None = None
        self._last_access_result: dict | None = None
        self._last_scanned_uid: str | None = None
        self._last_scanned_at = 0.0
        self._rfid_polling_paused_until = 0.0
        self._events: list[dict] = []
        self._auto_close_timer: threading.Timer | None = None

    def start(self) -> None:
        """Initialize the door servo and RFID worker."""
        with self._lock:
            if self._started:
                return
            self._stop_event.clear()
            self._started = True
            self._last_error = None
            self._initialize_servo_locked()
            self._move_door_locked(config.door.closed_angle, state="closed")

            access_status = self._access_service.get_status()
            if access_status["reader_enabled"]:
                self._worker_thread = threading.Thread(
                    target=self._worker_loop,
                    name="locker-rfid-worker",
                    daemon=True,
                )
                self._worker_thread.start()

    def stop(self) -> None:
        """Stop the RFID worker and release servo resources."""
        self._stop_event.set()

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None

        with self._lock:
            self._cancel_auto_close_locked()
            servo = self._door_servo
            self._door_servo = None
            self._door_servo_enabled = False
            self._started = False
            self._door_state = "unknown"
            self._door_angle = None

        if servo is None:
            return

        cleanup = getattr(servo, "cleanup", None) or getattr(servo, "close", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass

    def pause_rfid_polling(self, duration_seconds: float) -> None:
        """Temporarily pause background RFID scans."""
        with self._lock:
            self._rfid_polling_paused_until = max(
                self._rfid_polling_paused_until,
                time.monotonic() + max(duration_seconds, 0.0),
            )

    def open_door(self, *, source: str = "api", access_result: dict | None = None) -> dict:
        """Open the door and record an event."""
        with self._lock:
            event = self._open_door_locked(source=source, access_result=access_result)
            return copy.deepcopy(event)

    def close_door(self, *, source: str = "api") -> dict:
        """Close the door, then refresh occupancy state."""
        measurement = None
        with self._lock:
            event = self._close_door_locked(source=source)

        if self._occupancy_service is not None:
            measurement = self._occupancy_service.measure_once(door_state="closed")

        if measurement is not None:
            with self._lock:
                event["occupancy"] = measurement
                self._events[0] = copy.deepcopy(event)
                return copy.deepcopy(event)

        return copy.deepcopy(event)

    def process_scanned_uid(
        self,
        uid: str,
        *,
        source: str = "rfid",
        access_result: dict | None = None,
    ) -> dict | None:
        """Handle a scanned UID through access control and door workflow."""
        access_result = copy.deepcopy(access_result) if access_result is not None else self._access_service.authorize_uid(uid)
        with self._lock:
            if self._is_duplicate_scan_locked(access_result["uid"]):
                return None
            self._remember_scan_locked(access_result["uid"])
            self._last_access_result = copy.deepcopy(access_result)
            if access_result["allowed"]:
                return copy.deepcopy(self._open_door_locked(source=source, access_result=access_result))

            event = self._record_event_locked(
                {
                    "type": "access_denied",
                    "source": source,
                    "uid": access_result["uid"],
                    "allowed": False,
                    "reason": access_result["reason"],
                    "timestamp": time.time(),
                }
            )
            return copy.deepcopy(event)

    def note_no_card_present(self) -> None:
        """Clear duplicate-scan latch after the reader sees no card."""
        with self._lock:
            self._last_scanned_uid = None
            self._last_scanned_at = 0.0

    def list_events(self, limit: int = 30) -> list[dict]:
        """Return recent locker events."""
        with self._lock:
            return copy.deepcopy(self._events[: max(limit, 0)])

    def get_status(self) -> dict:
        """Return current locker, RFID, and occupancy status."""
        occupancy_status = (
            self._occupancy_service.get_status(door_state=self._door_state)
            if self._occupancy_service is not None
            else None
        )
        return {
            "started": self._started,
            "door_servo_enabled": self._door_servo_enabled,
            "door_state": self._door_state,
            "current_angle": round(self._door_angle, 2) if self._door_angle is not None else None,
            "last_error": self._last_error,
            "last_access_result": copy.deepcopy(self._last_access_result),
            "door_angles": {
                "closed": config.door.closed_angle,
                "open": config.door.open_angle,
            },
            "rfid": self._access_service.get_status(),
            "occupancy": occupancy_status,
            "recent_events": self.list_events(limit=10),
        }

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            pause_seconds = self._rfid_pause_remaining()
            if pause_seconds > 0:
                self._stop_event.wait(min(pause_seconds, 0.2))
                continue

            try:
                access_result = self._access_service.scan_and_authorize(
                    timeout=config.rfid.scan_timeout_seconds,
                )
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
                self._stop_event.wait(0.1)
                continue

            if access_result is None:
                self.note_no_card_present()
                continue

            self.process_scanned_uid(
                access_result["uid"],
                source="rfid",
                access_result=access_result,
            )

    def _initialize_servo_locked(self) -> None:
        self._door_servo = None
        self._door_servo_enabled = False

        if not config.door.enabled:
            self._last_error = "door control disabled in config"
            return

        if config.gpio.door_servo_pin is None:
            self._last_error = "door servo pin is not configured"
            return

        try:
            self._door_servo = self._servo_factory(
                config.gpio.door_servo_pin,
                min_angle=config.door.min_angle,
                max_angle=config.door.max_angle,
            )
            self._door_servo_enabled = True
            self._last_error = None
        except Exception as error:
            self._door_servo = None
            self._door_servo_enabled = False
            self._last_error = str(error)

    def _open_door_locked(self, *, source: str, access_result: dict | None) -> dict:
        self._cancel_auto_close_locked()
        self._move_door_locked(config.door.open_angle, state="open")
        event = {
            "type": "door_opened",
            "source": source,
            "uid": None if access_result is None else access_result["uid"],
            "allowed": True if access_result is None else access_result["allowed"],
            "reason": "manual_open" if access_result is None else access_result["reason"],
            "timestamp": time.time(),
        }
        recorded_event = self._record_event_locked(event)
        self._schedule_auto_close_locked()
        return recorded_event

    def _close_door_locked(self, *, source: str) -> dict:
        self._cancel_auto_close_locked()
        self._move_door_locked(config.door.closed_angle, state="closed")
        return self._record_event_locked(
            {
                "type": "door_closed",
                "source": source,
                "uid": None,
                "allowed": True,
                "reason": "manual_close" if source == "api" else source,
                "timestamp": time.time(),
            }
        )

    def _move_door_locked(self, target_angle: float, *, state: str) -> None:
        clamped_target = self._clamp(target_angle, config.door.min_angle, config.door.max_angle)
        servo = self._door_servo

        if servo is not None and self._door_servo_enabled:
            try:
                servo.move_to(
                    clamped_target,
                    step=max(config.door.move_step, 1.0),
                    delay=max(config.door.move_delay, 0.0),
                    release=True,
                )
            except Exception as error:
                self._last_error = str(error)
                return

        self._door_angle = clamped_target
        self._door_state = state

    def _record_event_locked(self, event: dict) -> dict:
        self._events.insert(0, copy.deepcopy(event))
        del self._events[50:]
        return event

    def _is_duplicate_scan_locked(self, uid: str) -> bool:
        return self._last_scanned_uid == uid

    def _remember_scan_locked(self, uid: str) -> None:
        self._last_scanned_uid = uid
        self._last_scanned_at = time.monotonic()

    def _rfid_pause_remaining(self) -> float:
        with self._lock:
            remaining = self._rfid_polling_paused_until - time.monotonic()
        return max(remaining, 0.0)

    def _schedule_auto_close_locked(self) -> None:
        delay_seconds = max(config.door.auto_close_seconds, 0.0)
        if delay_seconds <= 0:
            return

        self._auto_close_timer = threading.Timer(delay_seconds, self._auto_close_from_timer)
        self._auto_close_timer.daemon = True
        self._auto_close_timer.start()

    def _cancel_auto_close_locked(self) -> None:
        timer = self._auto_close_timer
        self._auto_close_timer = None
        if timer is not None:
            timer.cancel()

    def _auto_close_from_timer(self) -> None:
        self.close_door(source="auto_close")

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
