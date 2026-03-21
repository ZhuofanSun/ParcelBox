"""Hardware button service for snapshot triggers."""

from __future__ import annotations

import copy
import threading
import time

from config import config
from drivers.button import Button


class ButtonService:
    """Watch a GPIO button, capture snapshots, and expose the latest event."""

    def __init__(
        self,
        snapshot_callback=None,
        button_factory=Button,
    ) -> None:
        self._snapshot_callback = snapshot_callback
        self._button_factory = button_factory
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._started = False
        self._button = None
        self._button_enabled = False
        self._last_error: str | None = None
        self._latest_event: dict | None = None
        self._event_counter = 0

    def start(self) -> None:
        """Initialize the button watcher and start the worker."""
        with self._lock:
            if self._started:
                return

            self._stop_event.clear()
            self._started = True
            self._last_error = None
            self._initialize_button_locked()

            if not self._button_enabled:
                return

            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="button-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def stop(self) -> None:
        """Stop the button worker and release GPIO resources."""
        self._stop_event.set()

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None

        with self._lock:
            self._cleanup_button_locked()
            self._started = False

    def get_status(self) -> dict:
        """Return current button service state."""
        with self._lock:
            return {
                "started": self._started,
                "enabled": self._button_enabled,
                "pin": config.gpio.button_pin,
                "last_error": self._last_error,
                "latest_event": copy.deepcopy(self._latest_event),
            }

    def get_latest_event(self) -> dict | None:
        """Return the latest button event."""
        with self._lock:
            return copy.deepcopy(self._latest_event)

    def _initialize_button_locked(self) -> None:
        self._button = None
        self._button_enabled = False

        pin = config.gpio.button_pin
        if pin is None:
            self._last_error = "button pin is not configured"
            return

        try:
            self._button = self._button_factory(pin)
            self._button_enabled = True
            self._last_error = None
        except Exception as error:
            self._button = None
            self._button_enabled = False
            self._last_error = str(error)

    def _cleanup_button_locked(self) -> None:
        button = self._button
        self._button = None
        self._button_enabled = False
        if button is None:
            return

        cleanup = getattr(button, "cleanup", None) or getattr(button, "close", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            button = self._button
            if button is None:
                self._stop_event.wait(0.1)
                continue

            try:
                pressed = button.wait_for_press(timeout=0.1, poll_interval=0.02)
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
                self._stop_event.wait(0.1)
                continue

            if not pressed:
                continue

            self._record_button_press()

            try:
                button.wait_for_release(timeout=1.0, poll_interval=0.02)
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)

            self._stop_event.wait(0.15)

    def _record_button_press(self) -> None:
        snapshot = None
        snapshot_error = None

        if self._snapshot_callback is not None:
            try:
                snapshot = self._snapshot_callback()
            except Exception as error:
                snapshot_error = str(error)

        if isinstance(snapshot, dict):
            snapshot.setdefault("trigger", "button")
            snapshot.setdefault("source", "hardware_button")

        with self._lock:
            self._event_counter += 1
            event = {
                "id": self._event_counter,
                "type": "button_pressed",
                "source": "hardware_button",
                "timestamp": time.time(),
                "snapshot": copy.deepcopy(snapshot),
            }
            if snapshot_error is not None:
                event["snapshot_error"] = snapshot_error
                self._last_error = snapshot_error
            else:
                self._last_error = None
            self._latest_event = event
