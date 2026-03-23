"""RGB LED state-machine service."""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime

from config import config
from drivers.rgb_led import RgbLed

logger = logging.getLogger(__name__)


class LedService:
    """Drive the RGB LED according to the current locker and tracking state."""

    def __init__(
        self,
        vision_service=None,
        camera_mount_service=None,
        locker_service=None,
        button_service=None,
        led_factory=RgbLed,
    ) -> None:
        self._vision_service = vision_service
        self._camera_mount_service = camera_mount_service
        self._locker_service = locker_service
        self._button_service = button_service
        self._led_factory = led_factory
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._led = None
        self._enabled = False
        self._started = False
        self._last_error: str | None = None
        self._current_pattern = "off"
        self._last_logged_pattern: str | None = None

    def start(self) -> None:
        """Initialize the RGB LED and start the state loop."""
        with self._lock:
            if self._started:
                return

            self._stop_event.clear()
            self._started = True
            self._initialize_led_locked()
            if not self._enabled:
                logger.info("LED service started without hardware output: %s", self._last_error)
                return

            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="led-worker",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info(
                "LED service started on pins r=%s g=%s b=%s",
                config.gpio.rgb_red_pin,
                config.gpio.rgb_green_pin,
                config.gpio.rgb_blue_pin,
            )

    def stop(self) -> None:
        """Stop the LED worker and release GPIO resources."""
        self._stop_event.set()

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None

        with self._lock:
            led = self._led
            self._led = None
            self._enabled = False
            self._started = False
            self._current_pattern = "off"
            self._last_logged_pattern = None

        cleanup = getattr(led, "cleanup", None) or getattr(led, "close", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass
        logger.info("LED service stopped")

    def get_status(self) -> dict:
        """Return current LED service status."""
        with self._lock:
            current_rgb = None if self._led is None else self._led.current_rgb
            return {
                "started": self._started,
                "enabled": self._enabled,
                "pins": {
                    "red": config.gpio.rgb_red_pin,
                    "green": config.gpio.rgb_green_pin,
                    "blue": config.gpio.rgb_blue_pin,
                },
                "pattern": self._current_pattern,
                "current_rgb": current_rgb,
                "last_error": self._last_error,
            }

    def _initialize_led_locked(self) -> None:
        self._led = None
        self._enabled = False

        red_pin = config.gpio.rgb_red_pin
        green_pin = config.gpio.rgb_green_pin
        blue_pin = config.gpio.rgb_blue_pin
        if not config.led.enabled:
            self._last_error = "rgb led disabled in config"
            return
        if red_pin is None or green_pin is None or blue_pin is None:
            self._last_error = "rgb led pins are not fully configured"
            return

        try:
            self._led = self._led_factory(
                red_pin,
                green_pin,
                blue_pin,
                common_anode=config.led.common_anode,
                frequency=config.led.pwm_frequency,
            )
            self._enabled = True
            self._last_error = None
        except Exception as error:
            self._led = None
            self._enabled = False
            self._last_error = str(error)
            logger.warning("LED initialization failed: %s", error)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            try:
                pattern = self._determine_pattern(now)
                self._apply_pattern(pattern, now)
                with self._lock:
                    self._current_pattern = pattern
                    self._last_error = None
                self._log_pattern_change(pattern)
            except Exception as error:
                with self._lock:
                    self._current_pattern = "error"
                    self._last_error = str(error)
                self._log_pattern_change("error")
                logger.warning("LED worker error: %s", error)

            self._stop_event.wait(max(config.led.update_interval_seconds, 0.02))

    def _determine_pattern(self, now: float) -> str:
        if self._has_error():
            return "error_red_fast_blink"
        if self._is_recent_denied(now):
            return "denied_red_fast_blink"
        if self._is_door_open():
            return "door_open_white_solid"
        if self._is_recent_button_request(now):
            return "button_pending_yellow_slow_blink"
        if self._is_tracking_active():
            return "tracking_blue_slow_blink"
        return "standby_green_breathe"

    def _apply_pattern(self, pattern: str, now: float) -> None:
        led = self._led
        if led is None:
            return

        if pattern == "door_open_white_solid":
            led.set_rgb(255, 255, 255)
            return

        if pattern in {"error_red_fast_blink", "denied_red_fast_blink"}:
            if self._blink_on(now, config.led.fast_blink_cycle_seconds):
                led.set_rgb(255, 0, 0)
            else:
                led.off()
            return

        if pattern == "button_pending_yellow_slow_blink":
            if self._blink_on(now, config.led.slow_blink_cycle_seconds):
                led.set_rgb(255, 180, 0)
            else:
                led.off()
            return

        if pattern == "tracking_blue_slow_blink":
            if self._blink_on(now, config.led.slow_blink_cycle_seconds):
                led.set_rgb(0, 0, 255)
            else:
                led.off()
            return

        if pattern == "standby_green_breathe":
            green_value = self._breathe_value(now, config.led.standby_breath_cycle_seconds)
            led.set_rgb(0, green_value, 0)
            return

        led.off()

    @staticmethod
    def _blink_on(now: float, cycle_seconds: float) -> bool:
        cycle = max(cycle_seconds, 0.1)
        return (now % cycle) < (cycle / 2)

    @staticmethod
    def _breathe_value(now: float, cycle_seconds: float) -> int:
        cycle = max(cycle_seconds, 0.2)
        phase = (now % cycle) / cycle
        intensity = (math.sin(phase * 2 * math.pi - math.pi / 2) + 1) / 2
        return int(32 + intensity * 160)

    def _has_error(self) -> bool:
        locker_state = self._locker_service.get_indicator_state() if self._locker_service is not None else None
        if locker_state is not None and locker_state.get("last_error"):
            return True

        if self._camera_mount_service is not None:
            mount_status = self._camera_mount_service.get_status()
            if mount_status.get("last_error"):
                return True

        if self._vision_service is not None:
            payload = self._vision_service.get_boxes()
            if payload.get("status") in {"camera_error", "detector_error"}:
                return True

        return False

    def _is_recent_denied(self, now: float) -> bool:
        if self._locker_service is None:
            return False

        locker_state = self._locker_service.get_indicator_state()
        access_result = locker_state.get("last_access_result")
        if not isinstance(access_result, dict) or access_result.get("allowed", True):
            return False

        checked_at = access_result.get("checked_at")
        checked_at_epoch = self._timestamp_to_epoch(checked_at)
        if checked_at_epoch is None:
            return False
        return now - checked_at_epoch <= max(config.led.denied_flash_seconds, 0.0)

    def _is_door_open(self) -> bool:
        if self._locker_service is None:
            return False
        return self._locker_service.get_indicator_state().get("door_state") == "open"

    def _is_recent_button_request(self, now: float) -> bool:
        if self._button_service is None:
            return False

        event = self._button_service.get_latest_event()
        if not isinstance(event, dict):
            return False
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            return False
        return now - float(timestamp) <= max(config.led.button_pending_seconds, 0.0)

    def _is_tracking_active(self) -> bool:
        payload = self._vision_service.get_boxes() if self._vision_service is not None else {}
        active_mode = payload.get("active_mode")
        if active_mode in {"face", "face_hold"}:
            return True

        if self._camera_mount_service is None:
            return False
        advice = self._camera_mount_service.get_latest_advice()
        return advice.get("status") in {"tracking", "centered", "searching"}

    def _log_pattern_change(self, pattern: str) -> None:
        with self._lock:
            if pattern == self._last_logged_pattern:
                return
            self._last_logged_pattern = pattern
        logger.info("LED pattern changed to %s", pattern)

    @staticmethod
    def _timestamp_to_epoch(value) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).timestamp()
        except Exception:
            return None
