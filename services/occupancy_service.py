"""Locker occupancy evaluation service."""

from __future__ import annotations

import copy
import logging
import threading
import time

from config import config
from drivers.ultrasonic_sensor import UltrasonicSensor

logger = logging.getLogger(__name__)


class OccupancyService:
    """Measure and classify locker occupancy from ultrasonic readings."""

    def __init__(self, sensor_factory=UltrasonicSensor) -> None:
        self._sensor_factory = sensor_factory
        self._lock = threading.Lock()
        self._started = False
        self._sensor = None
        self._sensor_enabled = False
        self._last_error: str | None = None
        self._latest_measurement = self._build_unavailable_result(reason="not_started")

    def start(self) -> None:
        """Initialize the ultrasonic sensor if available."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._initialize_sensor_locked()
            logger.info("Occupancy service started: enabled=%s", self._sensor_enabled)

    def stop(self) -> None:
        """Release ultrasonic sensor resources."""
        with self._lock:
            sensor = self._sensor
            self._sensor = None
            self._sensor_enabled = False
            self._started = False
            self._latest_measurement = self._build_unavailable_result(reason="stopped")

        if sensor is None:
            return

        cleanup = getattr(sensor, "cleanup", None) or getattr(sensor, "close", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass
        logger.info("Occupancy service stopped")

    def measure_once(self, *, door_state: str | None = None) -> dict:
        """Capture one occupancy measurement and classify it."""
        with self._lock:
            sensor = self._sensor
            sensor_enabled = self._sensor_enabled

        if not sensor_enabled or sensor is None:
            result = self._build_unavailable_result(reason="sensor_unavailable")
            with self._lock:
                self._latest_measurement = result
            return copy.deepcopy(result)

        try:
            distance_cm = sensor.measure_distance_cm(
                samples=config.ultrasonic.sample_count,
                sample_interval=config.ultrasonic.sample_interval,
                method="average",
            )
        except Exception as error:
            result = self._build_unavailable_result(reason="measure_error", error=str(error))
            with self._lock:
                self._last_error = str(error)
                self._latest_measurement = result
            logger.warning("Ultrasonic measure failed: %s", error)
            return copy.deepcopy(result)

        result = self._classify_distance(distance_cm, door_state=door_state)
        with self._lock:
            self._last_error = None
            self._latest_measurement = result
        logger.info(
            "Ultrasonic measured: door_state=%s distance_cm=%s state=%s reason=%s",
            door_state,
            result.get("distance_cm"),
            result.get("state"),
            result.get("reason"),
        )
        return copy.deepcopy(result)

    def get_status(self, *, door_state: str | None = None) -> dict:
        """Return occupancy-service state and latest measurement."""
        with self._lock:
            measurement = copy.deepcopy(self._latest_measurement)
            return {
                "started": self._started,
                "enabled": self._sensor_enabled,
                "last_error": self._last_error,
                "latest_measurement": self._apply_door_state_context(measurement, door_state=door_state),
            }

    def _initialize_sensor_locked(self) -> None:
        self._sensor = None
        self._sensor_enabled = False

        trigger_pin = config.gpio.ultrasonic_trigger_pin
        echo_pin = config.gpio.ultrasonic_echo_pin
        if trigger_pin is None or echo_pin is None:
            self._last_error = "ultrasonic pins are not configured"
            self._latest_measurement = self._build_unavailable_result(reason="pins_unconfigured")
            return

        try:
            self._sensor = self._sensor_factory(trigger_pin=trigger_pin, echo_pin=echo_pin)
            self._sensor_enabled = True
            self._last_error = None
            self._latest_measurement = self._build_unavailable_result(reason="warming_up")
            logger.info(
                "Ultrasonic sensor initialized: trigger_pin=%s echo_pin=%s",
                trigger_pin,
                echo_pin,
            )
        except Exception as error:
            self._last_error = str(error)
            self._latest_measurement = self._build_unavailable_result(reason="sensor_error", error=str(error))
            logger.warning("Ultrasonic sensor initialization failed: %s", error)

    def _classify_distance(self, distance_cm: float | None, *, door_state: str | None = None) -> dict:
        now = time.time()
        if distance_cm is None:
            return {
                "state": "unknown",
                "reason": "no_echo",
                "distance_cm": None,
                "measured_at": now,
            }

        result = {
            "state": "unknown",
            "reason": "distance_captured",
            "distance_cm": round(distance_cm, 2),
            "measured_at": now,
        }
        return self._apply_door_state_context(result, door_state=door_state)

    @staticmethod
    def _apply_door_state_context(measurement: dict, *, door_state: str | None = None) -> dict:
        distance_cm = measurement.get("distance_cm")
        if distance_cm is None:
            return measurement

        occupied_threshold = config.ultrasonic.occupied_threshold_cm
        normalized = dict(measurement)
        if distance_cm <= occupied_threshold:
            normalized["state"] = "occupied"
            normalized["reason"] = "distance_below_occupied_threshold"
            return normalized

        if door_state == "closed":
            normalized["state"] = "empty"
            normalized["reason"] = "distance_above_occupied_threshold_door_closed"
            return normalized

        if door_state == "open":
            normalized["state"] = "door_not_closed"
            normalized["reason"] = "distance_above_occupied_threshold_door_open"
            return normalized

        normalized["state"] = "unknown"
        normalized["reason"] = "clear_distance_unknown_door_state"
        return normalized

    @staticmethod
    def _build_unavailable_result(*, reason: str, error: str | None = None) -> dict:
        return {
            "state": "unknown",
            "reason": reason,
            "distance_cm": None,
            "measured_at": time.time(),
            "error": error,
        }
