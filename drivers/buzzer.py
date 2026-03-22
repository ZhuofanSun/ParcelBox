"""Active buzzer driver.

Notes:
- This driver assumes the buzzer is switched by a GPIO-controlled transistor stage.
- Timing is blocking. Put longer alarm patterns in the service layer if needed.
"""

import time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - only hit off Raspberry Pi
    GPIO = None


class Buzzer:
    """Simple driver for an active buzzer."""

    def __init__(self, pin: int, active_high: bool = True, gpio_module=None) -> None:
        """
        Initialize the buzzer.

        Args:
            pin: BCM GPIO pin connected to the buzzer control circuit.
            active_high: If True, HIGH turns the buzzer on. If False, LOW turns it on.
            gpio_module: Optional GPIO-compatible module for testing or mocking.
        """
        self.pin = pin
        self.active_high = active_high
        self._gpio = gpio_module or GPIO
        self._is_on = False

        if self._gpio is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install it on the Raspberry Pi or "
                "pass a compatible gpio_module for testing."
            )

        if self._gpio.getmode() is None:
            self._gpio.setmode(self._gpio.BCM)

        initial_level = self._gpio.LOW if self.active_high else self._gpio.HIGH
        self._gpio.setup(self.pin, self._gpio.OUT, initial=initial_level)

    @property
    def is_on(self) -> bool:
        """Return whether the buzzer is currently on."""
        return self._is_on

    def on(self) -> None:
        """Turn the buzzer on."""
        level = self._gpio.HIGH if self.active_high else self._gpio.LOW
        self._gpio.output(self.pin, level)
        self._is_on = True

    def off(self) -> None:
        """Turn the buzzer off."""
        level = self._gpio.LOW if self.active_high else self._gpio.HIGH
        self._gpio.output(self.pin, level)
        self._is_on = False

    def beep(self, duration: float = 0.2, repeat: int = 1, interval: float = 0.1) -> None:
        """
        Beep the buzzer for a given duration and repeat count.

        Args:
            duration: How long each beep stays on, in seconds.
            repeat: Number of beeps to play.
            interval: Delay between beeps, in seconds.
        """
        if duration < 0:
            raise ValueError("duration must be >= 0")
        if repeat < 1:
            raise ValueError("repeat must be >= 1")
        if interval < 0:
            raise ValueError("interval must be >= 0")

        for index in range(repeat):
            self.on()
            time.sleep(duration)
            self.off()

            if index < repeat - 1:
                time.sleep(interval)

    def beep_pattern(self, pattern: list[float], interval: float = 0.1) -> None:
        """
        Play a simple blocking beep pattern.

        Args:
            pattern: List of beep durations in seconds.
            interval: Delay between each beep, in seconds.
        """
        if not pattern:
            raise ValueError("pattern must not be empty")
        if interval < 0:
            raise ValueError("interval must be >= 0")

        for index, duration in enumerate(pattern):
            if duration < 0:
                raise ValueError("pattern durations must be >= 0")

            self.on()
            time.sleep(duration)
            self.off()

            if index < len(pattern) - 1:
                time.sleep(interval)

    def cleanup(self) -> None:
        """Turn the buzzer off and release the GPIO pin."""
        self.off()
        self._gpio.cleanup(self.pin)

    def close(self) -> None:
        """Alias of cleanup()."""
        self.cleanup()


if __name__ == "__main__":
    TEST_PIN = 25

    buzzer = Buzzer(TEST_PIN)
    try:
        buzzer.beep()  # 默认 0.2秒
        time.sleep(0.5)
        buzzer.beep(0.1, 3, 0.1)  # 响0.1秒，间隔 0.1，重复三次
        time.sleep(0.5)
        buzzer.beep_pattern([0.1, 0.1, 0.3], 0.1)  # 一个短短长的简单模式
    finally:
        buzzer.cleanup()
