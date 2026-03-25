"""Locker door workflow orchestration."""

from __future__ import annotations

import copy
import logging
import threading
import time

from config import config
from drivers.servo import Servo
from services.access_service import AccessService
from services.occupancy_service import OccupancyService

logger = logging.getLogger(__name__)


class LockerService:
    """Coordinate RFID authorization, door servo moves, and occupancy checks."""

    def __init__(
        self,
        access_service: AccessService,
        occupancy_service: OccupancyService | None = None,
        servo_factory=Servo,
        snapshot_callback=None,
        alert_callback=None,
        event_store=None,
    ) -> None:
        self._access_service = access_service
        self._occupancy_service = occupancy_service
        self._servo_factory = servo_factory
        self._snapshot_callback = snapshot_callback
        self._alert_callback = alert_callback
        self._event_store = event_store
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
            if access_status["enabled"]:
                self._worker_thread = threading.Thread(
                    target=self._worker_loop,
                    name="locker-rfid-worker",
                    daemon=True,
                )
                self._worker_thread.start()
            logger.info(
                "Locker service started: servo_enabled=%s reader_enabled=%s",
                self._door_servo_enabled,
                access_status["reader_enabled"],
            )

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
        logger.info("Locker service stopped")

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
            logger.info(
                "Door opened: source=%s access_uid=%s",
                source,
                None if access_result is None else access_result.get("uid"),
            )
            return copy.deepcopy(event)

    def close_door(self, *, source: str = "api") -> dict:
        """Close the door, then refresh occupancy state."""
        with self._lock:
            self._cancel_auto_close_locked()
            self._move_door_locked(config.door.closed_angle, state="closed")
            event = {
                "type": "door_closed",
                "source": source,
                "uid": None,
                "allowed": True,
                "reason": "manual_close" if source == "api" else source,
                "timestamp": time.time(),
            }

        measurement = None
        if self._occupancy_service is not None:
            measurement = self._occupancy_service.measure_once(door_state="closed")

        if measurement is not None:
            event["occupancy"] = measurement

        with self._lock:
            recorded_event = self._persist_door_closed_event_locked(event)
            logger.info(
                "Door closed: source=%s auto_closed=%s occupancy=%s distance_cm=%s",
                source,
                source == "auto_close",
                None if measurement is None else measurement.get("state"),
                None if measurement is None else measurement.get("distance_cm"),
            )
            return copy.deepcopy(recorded_event)

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
                logger.info("RFID duplicate scan ignored: uid=%s source=%s", access_result["uid"], source)
                return None
            self._remember_scan_locked(access_result["uid"])
        logger.info(
            "RFID scan accepted for processing: uid=%s source=%s allowed=%s reason=%s",
            access_result["uid"],
            source,
            access_result["allowed"],
            access_result["reason"],
        )
        snapshot = self.capture_snapshot_for_card_action(source=source, uid=access_result["uid"])
        with self._lock:
            self._last_access_result = copy.deepcopy(access_result)
            if access_result["allowed"]:
                return copy.deepcopy(
                    self._open_door_locked(
                        source=source,
                        access_result=access_result,
                        snapshot=snapshot,
                    )
                )

            event = {
                "type": "access_denied",
                "source": source,
                "uid": access_result["uid"],
                "allowed": False,
                "reason": access_result["reason"],
                "timestamp": time.time(),
            }
            if snapshot is not None:
                event["snapshot"] = snapshot

            event = self._persist_access_denied_event_locked(event)
            logger.info(
                "Access denied event recorded: uid=%s source=%s reason=%s",
                access_result["uid"],
                source,
                access_result["reason"],
            )
            if self._alert_callback is not None:
                try:
                    self._alert_callback(copy.deepcopy(event))
                except Exception as error:
                    logger.warning("Access-denied alert callback failed: %s", error)
            return copy.deepcopy(event)

    def note_no_card_present(self) -> None:
        """Clear duplicate-scan latch after the reader sees no card."""
        with self._lock:
            had_latch = self._last_scanned_uid is not None
            self._last_scanned_uid = None
            self._last_scanned_at = 0.0
        if had_latch:
            logger.info("RFID duplicate-scan latch cleared after no-card read")

    def capture_snapshot_for_card_action(self, *, source: str, uid: str | None = None) -> dict | None:
        """Capture one snapshot for a card-present event if camera capture is available."""
        if self._snapshot_callback is None:
            return None

        try:
            snapshot = self._snapshot_callback()
        except Exception as error:
            with self._lock:
                self._last_error = str(error)
            logger.warning("Card-action snapshot failed: source=%s uid=%s error=%s", source, uid, error)
            return None

        if isinstance(snapshot, dict):
            snapshot.setdefault("trigger", "rfid")
            snapshot.setdefault("source", source)
            if uid is not None:
                snapshot.setdefault("uid", uid)
        logger.info(
            "Card-action snapshot captured: source=%s uid=%s filename=%s",
            source,
            uid,
            None if snapshot is None else snapshot.get("filename"),
        )
        return snapshot

    def list_events(self, limit: int = 30) -> list[dict]:
        """Return recent locker events."""
        if self._event_store is not None:
            stored_events = self._event_store.list_events(limit=limit, category="locker")
            if stored_events:
                return stored_events
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
            "door_servo_backend": (
                getattr(self._door_servo, "backend_name", None) if self._door_servo is not None else None
            ),
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

    def get_indicator_state(self) -> dict:
        """Return lightweight state for LED / buzzer indicator logic."""
        with self._lock:
            return {
                "door_state": self._door_state,
                "last_error": self._last_error,
                "last_access_result": copy.deepcopy(self._last_access_result),
            }

    def _worker_loop(self) -> None:
        recoverable_error_streak = 0
        last_recovery_signature = None
        while not self._stop_event.is_set():
            pause_seconds = self._rfid_pause_remaining()
            if pause_seconds > 0:
                self._stop_event.wait(min(pause_seconds, 0.2))
                continue

            if not self._access_service.get_status()["reader_enabled"]:
                recovery = self._access_service.restart_reader()
                with self._lock:
                    self._last_error = recovery.get("last_error")
                signature = (bool(recovery.get("reader_enabled")), recovery.get("last_error"))
                if signature != last_recovery_signature:
                    logger.warning(
                        "RFID reader unavailable in worker loop: recovery attempted reader_enabled=%s last_error=%s",
                        recovery.get("reader_enabled"),
                        recovery.get("last_error"),
                    )
                    last_recovery_signature = signature
                self._stop_event.wait(1.0)
                continue

            try:
                access_result = self._access_service.scan_and_authorize(
                    timeout=config.rfid.scan_timeout_seconds,
                )
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
                if not self._is_recoverable_rfid_error(error):
                    logger.exception("RFID worker loop stopped by unexpected error")
                    return

                recoverable_error_streak += 1
                logger.warning(
                    "RFID worker loop recoverable error: %s (streak=%s)",
                    error,
                    recoverable_error_streak,
                )
                if recoverable_error_streak >= 3:
                    recovery = self._access_service.restart_reader()
                    logger.warning(
                        "RFID reader recovery attempted: reader_enabled=%s last_error=%s",
                        recovery.get("reader_enabled"),
                        recovery.get("last_error"),
                    )
                    if recovery.get("reader_enabled"):
                        recoverable_error_streak = 0
                        self._stop_event.wait(0.25)
                    else:
                        self._stop_event.wait(1.0)
                else:
                    self._stop_event.wait(0.1)
                continue

            if access_result is None:
                recoverable_error_streak = 0
                last_recovery_signature = None
                self.note_no_card_present()
                continue

            recoverable_error_streak = 0
            last_recovery_signature = None
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
            logger.info(
                "Door servo initialized on pin %s using backend %s",
                config.gpio.door_servo_pin,
                getattr(self._door_servo, "backend_name", None),
            )
        except Exception as error:
            self._door_servo = None
            self._door_servo_enabled = False
            self._last_error = str(error)
            logger.warning("Door servo initialization failed: %s", error)

    def _open_door_locked(
        self,
        *,
        source: str,
        access_result: dict | None,
        snapshot: dict | None = None,
    ) -> dict:
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
        if snapshot is not None:
            event["snapshot"] = snapshot
        recorded_event = self._persist_door_opened_event_locked(event)
        self._schedule_auto_close_locked()
        return recorded_event

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
                logger.warning("Door servo move failed: target=%s state=%s error=%s", clamped_target, state, error)
                return

        self._door_angle = clamped_target
        self._door_state = state
        logger.info("Door state set: state=%s angle=%.2f", state, clamped_target)

    def _persist_access_denied_event_locked(self, event: dict) -> dict:
        stored_event = copy.deepcopy(event)
        if self._event_store is not None:
            stored_attempt = self._event_store.record_access_attempt(
                card_uid=stored_event["uid"],
                source=stored_event["source"],
                allowed=False,
                reason=stored_event["reason"],
                checked_at=stored_event.get("timestamp"),
                snapshot=stored_event.get("snapshot"),
            )
            if stored_attempt.get("id") is not None:
                stored_event["storage_id"] = int(stored_attempt["id"])
                stored_event["storage_category"] = "locker"
            if stored_attempt.get("snapshot") is not None:
                stored_event["snapshot"] = stored_attempt["snapshot"]
        self._events.insert(0, copy.deepcopy(stored_event))
        del self._events[50:]
        return stored_event

    def _persist_door_opened_event_locked(self, event: dict) -> dict:
        stored_event = copy.deepcopy(event)
        if self._event_store is not None:
            access_attempt_id = None
            if stored_event.get("uid") is not None:
                stored_attempt = self._event_store.record_access_attempt(
                    card_uid=stored_event["uid"],
                    source=stored_event["source"],
                    allowed=bool(stored_event.get("allowed", True)),
                    reason=stored_event.get("reason", "granted"),
                    checked_at=stored_event.get("timestamp"),
                    snapshot=stored_event.get("snapshot"),
                )
                access_attempt_id = stored_attempt.get("id")
                if stored_attempt.get("snapshot") is not None:
                    stored_event["snapshot"] = stored_attempt["snapshot"]
            stored_session = self._event_store.open_door_session(
                access_attempt_id=access_attempt_id,
                open_source=stored_event["source"],
                opened_at=stored_event.get("timestamp"),
            )
            if stored_session.get("id") is not None:
                stored_event["storage_id"] = int(stored_session["id"])
                stored_event["storage_category"] = "locker"
        self._events.insert(0, copy.deepcopy(stored_event))
        del self._events[50:]
        return stored_event

    def _persist_door_closed_event_locked(self, event: dict) -> dict:
        stored_event = copy.deepcopy(event)
        if self._event_store is not None:
            stored_session = self._event_store.close_door_session(
                close_source=stored_event["source"],
                closed_at=stored_event.get("timestamp"),
                auto_closed=stored_event.get("source") == "auto_close",
                occupancy=stored_event.get("occupancy"),
                create_if_missing=True,
            )
            if stored_session.get("id") is not None:
                stored_event["storage_id"] = int(stored_session["id"])
                stored_event["storage_category"] = "locker"
        self._events.insert(0, copy.deepcopy(stored_event))
        del self._events[50:]
        return stored_event

    def _is_duplicate_scan_locked(self, uid: str) -> bool:
        return self._last_scanned_uid == uid

    def _remember_scan_locked(self, uid: str) -> None:
        self._last_scanned_uid = uid
        self._last_scanned_at = time.monotonic()

    def _rfid_pause_remaining(self) -> float:
        with self._lock:
            remaining = self._rfid_polling_paused_until - time.monotonic()
        return max(remaining, 0.0)

    @staticmethod
    def _is_recoverable_rfid_error(error: Exception) -> bool:
        return isinstance(error, (RuntimeError, OSError))

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
