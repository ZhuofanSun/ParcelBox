"""Non-blocking buzzer orchestration service."""

from __future__ import annotations

import threading

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
        self._queue: list[tuple[float, int, float]] = []

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
                "last_error": self._last_error,
            }

    def request_beep(self, duration: float, repeat: int = 1, interval: float = 0.0) -> bool:
        """Queue one beep pattern for background playback."""
        with self._condition:
            if not self._enabled or not self._started:
                return False
            self._queue.append((max(duration, 0.0), max(int(repeat), 1), max(interval, 0.0)))
            self._condition.notify()
            return True

    def beep_card_detected(self) -> bool:
        """Play the short RC522 card-detected prompt."""
        return self.request_beep(
            config.buzzer.card_detect_beep_duration,
            repeat=config.buzzer.card_detect_beep_repeat,
            interval=config.buzzer.card_detect_beep_interval,
        )

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
                duration, repeat, interval = self._queue.pop(0)
                buzzer = self._buzzer

            if buzzer is None:
                continue

            try:
                buzzer.beep(duration=duration, repeat=repeat, interval=interval)
                with self._lock:
                    self._last_error = None
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
