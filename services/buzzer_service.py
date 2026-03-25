"""Non-blocking buzzer orchestration service."""

from __future__ import annotations

import threading
import time

from config import config
from drivers.buzzer import Buzzer


class BuzzerService:
    """Own the active buzzer and play short notification patterns in the background."""

    def __init__(self, buzzer_factory=Buzzer) -> None:
        self._buzzer_factory = buzzer_factory
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._buzzer = None
        self._enabled = False
        self._started = False
        self._last_error: str | None = None
        self._queue: list[dict] = []
        self._playback_generation = 0

    def start(self) -> None:
        """Initialize the buzzer and start the playback worker."""
        with self._lock:
            if self._started:
                return

            self._stop_event.clear()
            self._started = True
            self._initialize_buzzer_locked()
            if not self._enabled:
                return

            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="buzzer-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def stop(self) -> None:
        """Stop queued playback and release buzzer resources."""
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None

        with self._lock:
            buzzer = self._buzzer
            self._buzzer = None
            self._enabled = False
            self._started = False
            self._queue.clear()

        cleanup = getattr(buzzer, "cleanup", None) or getattr(buzzer, "close", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass

    def get_status(self) -> dict:
        """Return buzzer runtime status."""
        with self._lock:
            return {
                "started": self._started,
                "enabled": self._enabled,
                "pin": config.gpio.buzzer_pin,
                "queue_size": len(self._queue),
                "playback_generation": self._playback_generation,
                "last_error": self._last_error,
            }

    def request_beep(self, duration: float, repeat: int = 1, interval: float = 0.0) -> bool:
        """Queue one beep pattern for background playback."""
        pattern = [max(duration, 0.0)] * max(int(repeat), 1)
        return self.request_pattern(pattern, interval=interval)

    def request_pattern(self, pattern: list[float], *, interval: float = 0.0) -> bool:
        """Queue one beep pattern for background playback."""
        with self._condition:
            if not self._enabled or not self._started:
                return False
            normalized_pattern = [max(float(duration), 0.0) for duration in pattern if float(duration) >= 0.0]
            if not normalized_pattern:
                return False
            self._queue.append(
                {
                    "pattern": normalized_pattern,
                    "interval": max(float(interval), 0.0),
                    "generation": self._playback_generation,
                }
            )
            self._condition.notify()
            return True

    def beep_card_detected(self) -> bool:
        """Play the short RC522 card-detected prompt."""
        return self.request_beep(
            config.buzzer.card_detect_beep_duration,
            repeat=config.buzzer.card_detect_beep_repeat,
            interval=config.buzzer.card_detect_beep_interval,
        )

    def beep_unauthorized_card(self) -> bool:
        """Play the short double-beep for one unauthorized RFID scan."""
        return self.request_beep(
            config.alert.unauthorized_card_beep_duration,
            repeat=config.alert.unauthorized_card_beep_repeat,
            interval=config.alert.unauthorized_card_beep_interval,
        )

    def play_medium_alarm(self) -> bool:
        """Play the medium-severity button-burst alarm pattern."""
        return self.request_beep(
            config.alert.medium_alarm_beep_duration,
            repeat=config.alert.medium_alarm_beep_repeat,
            interval=config.alert.medium_alarm_beep_interval,
        )

    def play_severe_alarm(self) -> bool:
        """Play the severe repeated unauthorized-card alarm pattern."""
        return self.request_beep(
            config.alert.severe_alarm_beep_duration,
            repeat=config.alert.severe_alarm_beep_repeat,
            interval=config.alert.severe_alarm_beep_interval,
        )

    def silence(self) -> bool:
        """Stop queued playback and silence the active buzzer immediately."""
        with self._condition:
            if not self._started:
                return False
            self._queue.clear()
            self._playback_generation += 1
            self._condition.notify_all()
            buzzer = self._buzzer

        if buzzer is None:
            return False

        off = getattr(buzzer, "off", None)
        if callable(off):
            try:
                off()
            except Exception:
                pass
        return True

    def _initialize_buzzer_locked(self) -> None:
        self._buzzer = None
        self._enabled = False

        if not config.buzzer.enabled:
            self._last_error = "buzzer disabled in config"
            return

        if config.gpio.buzzer_pin is None:
            self._last_error = "buzzer pin is not configured"
            return

        try:
            self._buzzer = self._buzzer_factory(config.gpio.buzzer_pin)
            self._enabled = True
            self._last_error = None
        except Exception as error:
            self._buzzer = None
            self._enabled = False
            self._last_error = str(error)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._condition:
                while not self._queue and not self._stop_event.is_set():
                    self._condition.wait(timeout=0.2)
                if self._stop_event.is_set():
                    return
                request = self._queue.pop(0)
                buzzer = self._buzzer

            if buzzer is None:
                continue

            try:
                self._play_request(buzzer, request)
                with self._lock:
                    self._last_error = None
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)

    def _play_request(self, buzzer, request: dict) -> None:
        pattern = list(request.get("pattern") or [])
        interval = max(float(request.get("interval", 0.0)), 0.0)
        generation = int(request.get("generation", self._playback_generation))
        if not pattern:
            return

        on = getattr(buzzer, "on", None)
        off = getattr(buzzer, "off", None)
        if not callable(on) or not callable(off):
            duration = pattern[0]
            repeat = len(pattern)
            fallback_beep = getattr(buzzer, "beep", None)
            if callable(fallback_beep):
                fallback_beep(duration=duration, repeat=repeat, interval=interval)
            return

        for index, duration in enumerate(pattern):
            if self._should_abort_playback(generation):
                off()
                return
            on()
            if not self._sleep_interruptibly(duration, generation):
                off()
                return
            off()
            if index < len(pattern) - 1 and not self._sleep_interruptibly(interval, generation):
                off()
                return

    def _sleep_interruptibly(self, duration: float, generation: int) -> bool:
        deadline = time.monotonic() + max(duration, 0.0)
        while time.monotonic() < deadline:
            if self._should_abort_playback(generation):
                return False
            remaining = deadline - time.monotonic()
            time.sleep(min(0.02, max(remaining, 0.0)))
        return not self._should_abort_playback(generation)

    def _should_abort_playback(self, generation: int) -> bool:
        if self._stop_event.is_set():
            return True
        with self._lock:
            return generation != self._playback_generation
