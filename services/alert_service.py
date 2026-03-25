"""Runtime alarm orchestration for buzzer, search, and in-app alert events."""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections import deque

from config import config
from services.buzzer_service import BuzzerService

logger = logging.getLogger(__name__)


class AlertService:
    """Track burst conditions and emit local alarm events."""

    def __init__(self, buzzer_service: BuzzerService, camera_mount_service=None) -> None:
        self._buzzer_service = buzzer_service
        self._camera_mount_service = camera_mount_service
        self._lock = threading.Lock()
        self._event_counter = 0
        self._recent_events: deque[dict] = deque(maxlen=50)
        self._button_press_times: deque[float] = deque()
        self._denied_times: deque[float] = deque()
        self._button_burst_active = False
        self._denied_burst_active = False

    def handle_access_denied(self, event: dict | None) -> None:
        """Emit warning or severe alarms for one unauthorized card scan."""
        timestamp = self._coerce_event_timestamp(event)
        self._buzzer_service.beep_unauthorized_card()
        self._record_alarm_event(
            alarm_type="unauthorized_card_alarm",
            source="rfid",
            severity="warning",
            reason="single_unauthorized_card",
            timestamp=timestamp,
            event=event,
        )

        severe_triggered = False
        with self._lock:
            self._prune_times(self._denied_times, timestamp, config.alert.access_denied_burst_window_seconds)
            if len(self._denied_times) < max(config.alert.access_denied_burst_threshold, 1):
                self._denied_burst_active = False
            self._denied_times.append(timestamp)
            if (
                len(self._denied_times) >= max(config.alert.access_denied_burst_threshold, 1)
                and not self._denied_burst_active
            ):
                self._denied_burst_active = True
                severe_triggered = True

        search_started = self._request_search_once()
        if severe_triggered:
            self._buzzer_service.play_severe_alarm()
            self._record_alarm_event(
                alarm_type="access_denied_burst_alarm",
                source="rfid",
                severity="severe",
                reason="repeated_unauthorized_card",
                timestamp=timestamp,
                event=event,
                extra={"search_requested": search_started},
            )

    def handle_button_pressed(self, event: dict | None) -> None:
        """Raise one medium alarm when the hardware button is spammed."""
        timestamp = self._coerce_event_timestamp(event)
        alarm_triggered = False
        with self._lock:
            self._prune_times(self._button_press_times, timestamp, config.alert.button_press_burst_window_seconds)
            self._button_press_times.append(timestamp)
            if (
                len(self._button_press_times) >= max(config.alert.button_press_burst_threshold, 1)
                and not self._button_burst_active
            ):
                self._button_burst_active = True
                alarm_triggered = True

        if not alarm_triggered:
            return

        self._buzzer_service.play_medium_alarm()
        search_started = self._request_search_once()
        self._record_alarm_event(
            alarm_type="button_press_burst_alarm",
            source="hardware_button",
            severity="medium",
            reason="rapid_button_press_burst",
            timestamp=timestamp,
            event=event,
            extra={"search_requested": search_started},
        )
        if not search_started and not self._is_search_active():
            self._reset_button_burst_state()

    def on_alert_search_completed(self) -> None:
        """Reset burst-tracking state when an alert-triggered search finishes."""
        self._reset_button_burst_state()

    def silence(self) -> bool:
        """Stop active local alarm playback."""
        return self._buzzer_service.silence()

    def list_events(self, limit: int = 20) -> list[dict]:
        """Return recent in-memory alarm events, newest first."""
        safe_limit = max(int(limit), 0)
        with self._lock:
            events = list(self._recent_events)
        events.sort(key=lambda event: float(event.get("timestamp") or 0.0), reverse=True)
        return copy.deepcopy(events[:safe_limit])

    def _request_search_once(self) -> bool:
        if self._camera_mount_service is None:
            return False
        try:
            return bool(self._camera_mount_service.request_alert_search_once())
        except Exception as error:
            logger.warning("Alert-triggered search request failed: %s", error)
            return False

    def _is_search_active(self) -> bool:
        if self._camera_mount_service is None:
            return False
        try:
            return bool(self._camera_mount_service.is_search_active())
        except Exception:
            return False

    def _record_alarm_event(
        self,
        *,
        alarm_type: str,
        source: str,
        severity: str,
        reason: str,
        timestamp: float,
        event: dict | None = None,
        extra: dict | None = None,
    ) -> None:
        snapshot = copy.deepcopy(event.get("snapshot")) if isinstance(event, dict) and event.get("snapshot") else None
        uid = event.get("uid") if isinstance(event, dict) else None
        payload = {
            "id": self._next_event_id(),
            "type": alarm_type,
            "source": source,
            "severity": severity,
            "reason": reason,
            "timestamp": timestamp,
            "allowed": False,
        }
        if uid:
            payload["uid"] = uid
        if snapshot is not None:
            payload["snapshot"] = snapshot
        if extra:
            payload.update(copy.deepcopy(extra))
        with self._lock:
            self._recent_events.append(payload)

    def _next_event_id(self) -> int:
        with self._lock:
            self._event_counter += 1
            return self._event_counter

    def _reset_button_burst_state(self) -> None:
        with self._lock:
            self._button_press_times.clear()
            self._button_burst_active = False

    @staticmethod
    def _coerce_event_timestamp(event: dict | None) -> float:
        timestamp = None if not isinstance(event, dict) else event.get("timestamp")
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            return float(timestamp)
        return time.time()

    @staticmethod
    def _prune_times(values: deque[float], now: float, window_seconds: float) -> None:
        window = max(float(window_seconds), 0.0)
        if window <= 0:
            values.clear()
            return
        cutoff = now - window
        while values and values[0] < cutoff:
            values.popleft()
