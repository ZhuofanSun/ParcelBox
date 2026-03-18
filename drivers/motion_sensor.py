import time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - only hit off Raspberry Pi
    GPIO = None


class MotionSensor:
    """Simple driver for a PIR motion sensor."""

    def __init__(
        self,
        pin: int,
        active_high: bool = True,
        pull_up_down: str = "off",
        gpio_module=None,
    ) -> None:
        """
        Initialize the motion sensor.

        Args:
            pin: BCM GPIO pin connected to the sensor output.
            active_high: If True, HIGH means motion detected. If False, LOW means motion detected.
            pull_up_down: Internal resistor mode, supports "up", "down", or "off".
            gpio_module: Optional GPIO-compatible module for testing or mocking.
        """
        self.pin = pin
        self.active_high = active_high
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
    def is_motion_detected(self) -> bool:
        """Return whether motion is currently detected."""
        value = self.read()
        return value == self._gpio.HIGH if self.active_high else value == self._gpio.LOW

    def wait_for_motion(self, timeout: float = None, poll_interval: float = 0.05) -> bool:
        """
        Wait until motion is detected.

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
            if self.is_motion_detected:
                return True

            if timeout is not None and time.time() - start_time >= timeout:
                return False

            time.sleep(poll_interval)

    def wait_for_no_motion(self, timeout: float = None, poll_interval: float = 0.05) -> bool:
        """
        Wait until motion is no longer detected.

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
            if not self.is_motion_detected:
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
    TEST_PIN = 4

    sensor = MotionSensor(TEST_PIN)
    try:
        print("Waiting for motion...")
        while True:
            if sensor.wait_for_motion(0.1):
                print("Motion detected")
                sensor.wait_for_no_motion()
                print("Motion ended")  # 目标离开后再打印结束状态
    finally:
        sensor.cleanup()
