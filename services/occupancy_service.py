"""Locker occupancy evaluation service."""

from __future__ import annotations

import copy
import threading
import time

from config import config
from drivers.ultrasonic_sensor import UltrasonicSensor


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

    def measure_once(self) -> dict:
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
            return copy.deepcopy(result)

        result = self._classify_distance(distance_cm)
        with self._lock:
            self._last_error = None
            self._latest_measurement = result
        return copy.deepcopy(result)

    def get_status(self) -> dict:
        """Return occupancy-service state and latest measurement."""
        with self._lock:
            return {
                "started": self._started,
                "enabled": self._sensor_enabled,
                "last_error": self._last_error,
                "latest_measurement": copy.deepcopy(self._latest_measurement),
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
        except Exception as error:
            self._last_error = str(error)
            self._latest_measurement = self._build_unavailable_result(reason="sensor_error", error=str(error))

    def _classify_distance(self, distance_cm: float | None) -> dict:
        now = time.time()
        if distance_cm is None:
            return {
                "state": "unknown",
                "reason": "no_echo",
                "distance_cm": None,
                "measured_at": now,
            }

        occupied_threshold = config.ultrasonic.occupied_threshold_cm
        empty_threshold = config.ultrasonic.empty_threshold_cm

        if distance_cm <= occupied_threshold:
            state = "occupied"
            reason = "distance_below_occupied_threshold"
        elif distance_cm >= empty_threshold:
            state = "empty"
            reason = "distance_above_empty_threshold"
        else:
            previous_state = self._latest_measurement.get("state")
            if previous_state in {"occupied", "empty"}:
                state = previous_state
                reason = "hold_previous_state"
            else:
                state = "unknown"
                reason = "uncertain_range"

        return {
            "state": state,
            "reason": reason,
            "distance_cm": round(distance_cm, 2),
            "measured_at": now,
        }

    @staticmethod
    def _build_unavailable_result(*, reason: str, error: str | None = None) -> dict:
        return {
            "state": "unknown",
            "reason": reason,
            "distance_cm": None,
            "measured_at": time.time(),
            "error": error,
        }
