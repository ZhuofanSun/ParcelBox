import time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - only hit off Raspberry Pi
    GPIO = None


class Button:
    """Simple driver for a button input."""

    def __init__(
        self,
        pin: int,
        active_low: bool = True,
        pull_up_down: str = "up",
        gpio_module=None,
    ) -> None:
        """
        Initialize the button.

        Args:
            pin: BCM GPIO pin connected to the button signal.
            active_low: If True, LOW means pressed. If False, HIGH means pressed.
            pull_up_down: Internal resistor mode, supports "up", "down", or "off".
            gpio_module: Optional GPIO-compatible module for testing or mocking.
        """
        self.pin = pin
        self.active_low = active_low
        self.pull_up_down = pull_up_down
        self._gpio = gpio_module or GPIO

        if self._gpio is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install it on the Raspberry Pi or "
                "pass a compatible gpio_module for testing."
            )

        if self._gpio.getmode() is None:
            self._gpio.setmode(self._gpio.BCM)

        pull_mode = self._get_pull_mode(pull_up_down)

        if pull_mode is None:
            self._gpio.setup(self.pin, self._gpio.IN)
        else:
            self._gpio.setup(self.pin, self._gpio.IN, pull_up_down=pull_mode)

    def _get_pull_mode(self, pull_up_down: str):
        if pull_up_down == "up":
            return self._gpio.PUD_UP
        if pull_up_down == "down":
            return self._gpio.PUD_DOWN
        if pull_up_down == "off":
            return None
        raise ValueError('pull_up_down must be "up", "down", or "off"')

    def read(self) -> int:
        """Read the raw GPIO input level."""
        return self._gpio.input(self.pin)

    @property
    def is_pressed(self) -> bool:
        """Return whether the button is currently pressed."""
        value = self.read()
        return value == self._gpio.LOW if self.active_low else value == self._gpio.HIGH

    def wait_for_press(self, timeout: float = None, poll_interval: float = 0.01) -> bool:
        """
        Wait until the button is pressed.

        Args:
            timeout: Maximum wait time in seconds. None means wait forever.
            poll_interval: Delay between checks, in seconds.
        """
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be >= 0 or None")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")

        start_time = time.time()

        while True:
            if self.is_pressed:
                return True

            if timeout is not None and time.time() - start_time >= timeout:
                return False

            time.sleep(poll_interval)

    def cleanup(self) -> None:
        """Release the GPIO pin."""
        self._gpio.cleanup(self.pin)

    def close(self) -> None:
        """Alias of cleanup()."""
        self.cleanup()


if __name__ == "__main__":
    TEST_PIN = 27

    button = Button(TEST_PIN)
    try:
        print("Waiting for button press...")
        while True:
            if button.wait_for_press(0.1):
                print("Button pressed")
                time.sleep(0.3)  # 简单防抖，避免按住时连续触发
    finally:
        button.cleanup()
