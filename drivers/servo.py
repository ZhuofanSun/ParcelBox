import time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - only hit off Raspberry Pi
    GPIO = None


class Servo:
    """Simple driver for a standard servo motor."""

    def __init__(
        self,
        pin: int,
        min_angle: float = 0,
        max_angle: float = 160,
        min_pulse_width: float = 0.5,
        max_pulse_width: float = 2.0,
        frequency: int = 50,
        gpio_module=None,
    ) -> None:
        """
        Initialize the servo.

        Args:
            pin: BCM GPIO pin connected to the servo signal wire.
            min_angle: Minimum angle supported by this servo.
            max_angle: Maximum angle supported by this servo.
            min_pulse_width: Pulse width in milliseconds for min_angle.
            max_pulse_width: Pulse width in milliseconds for max_angle.
            frequency: PWM frequency in Hz. Standard servos usually use 50 Hz.
            gpio_module: Optional GPIO-compatible module for testing or mocking.
        """
        if min_angle >= max_angle:
            raise ValueError("min_angle must be smaller than max_angle")
        if min_pulse_width <= 0 or max_pulse_width <= 0:
            raise ValueError("pulse widths must be > 0")
        if min_pulse_width >= max_pulse_width:
            raise ValueError("min_pulse_width must be smaller than max_pulse_width")
        if frequency <= 0:
            raise ValueError("frequency must be > 0")

        self.pin = pin
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.min_pulse_width = min_pulse_width
        self.max_pulse_width = max_pulse_width
        self.frequency = frequency
        self._gpio = gpio_module or GPIO
        self._current_angle = None

        if self._gpio is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install it on the Raspberry Pi or "
                "pass a compatible gpio_module for testing."
            )

        if self._gpio.getmode() is None:
            self._gpio.setmode(self._gpio.BCM)

        self._gpio.setup(self.pin, self._gpio.OUT)
        self._pwm = self._gpio.PWM(self.pin, self.frequency)
        self._pwm.start(0)

    @property
    def current_angle(self):
        """Return the last angle sent to the servo."""
        return self._current_angle

    def _validate_angle(self, angle: float) -> None:
        if not self.min_angle <= angle <= self.max_angle:
            raise ValueError(
                f"angle must be between {self.min_angle} and {self.max_angle}"
            )

    def _angle_to_pulse_width(self, angle: float) -> float:
        angle_range = self.max_angle - self.min_angle
        pulse_range = self.max_pulse_width - self.min_pulse_width
        return self.min_pulse_width + ((angle - self.min_angle) / angle_range) * pulse_range

    def _pulse_width_to_duty_cycle(self, pulse_width: float) -> float:
        period_ms = 1000 / self.frequency
        return pulse_width / period_ms * 100

    def release(self) -> None:
        """Stop sending PWM to reduce jitter after moving."""
        self._pwm.ChangeDutyCycle(0)

    def set_angle(self, angle: float, settle_time: float = 0.3, release: bool = True) -> None:
        """
        Move the servo to a target angle.

        Args:
            angle: Target angle to move to.
            settle_time: Time in seconds to wait for the servo to reach the target.
            release: If True, stop PWM after the move to reduce jitter.
        """
        if settle_time < 0:
            raise ValueError("settle_time must be >= 0")

        self._validate_angle(angle)
        pulse_width = self._angle_to_pulse_width(angle)
        duty_cycle = self._pulse_width_to_duty_cycle(pulse_width)

        self._pwm.ChangeDutyCycle(duty_cycle)
        self._current_angle = angle

        if settle_time > 0:
            time.sleep(settle_time)

        if release:
            self.release()

    def center(self, settle_time: float = 0.3, release: bool = True) -> None:
        """
        Move the servo to the center angle.

        Args:
            settle_time: Time in seconds to wait for the servo to reach the target.
            release: If True, stop PWM after the move to reduce jitter.
        """
        center_angle = (self.min_angle + self.max_angle) / 2
        self.set_angle(center_angle, settle_time, release)

    def move_min(self, settle_time: float = 0.3, release: bool = True) -> None:
        """
        Move the servo to the minimum angle.

        Args:
            settle_time: Time in seconds to wait for the servo to reach the target.
            release: If True, stop PWM after the move to reduce jitter.
        """
        self.set_angle(self.min_angle, settle_time, release)

    def move_max(self, settle_time: float = 0.3, release: bool = True) -> None:
        """
        Move the servo to the maximum angle.

        Args:
            settle_time: Time in seconds to wait for the servo to reach the target.
            release: If True, stop PWM after the move to reduce jitter.
        """
        self.set_angle(self.max_angle, settle_time, release)

    def move_to(
        self,
        angle: float,
        step: float = 1,
        delay: float = 0.02,
        release: bool = True,
    ) -> None:
        """
        Move the servo gradually to a target angle.

        Args:
            angle: Final target angle.
            step: Angle step used for each small move.
            delay: Delay in seconds between steps.
            release: If True, stop PWM after the move to reduce jitter.
        """
        if step <= 0:
            raise ValueError("step must be > 0")
        if delay < 0:
            raise ValueError("delay must be >= 0")

        self._validate_angle(angle)

        if self._current_angle is None:
            self.set_angle(angle, 0.3, release)
            return

        current = self._current_angle

        if angle > current:
            while current < angle:
                current = min(current + step, angle)
                self.set_angle(current, 0, False)
                time.sleep(delay)
        else:
            while current > angle:
                current = max(current - step, angle)
                self.set_angle(current, 0, False)
                time.sleep(delay)

        self._current_angle = angle

        if release:
            self.release()

    def cleanup(self) -> None:
        """Stop PWM and release the GPIO pin."""
        self.release()
        self._pwm.stop()
        self._gpio.cleanup(self.pin)

    def close(self) -> None:
        """Alias of cleanup()."""
        self.cleanup()


if __name__ == "__main__":
    TEST_PIN = 18

    servo = Servo(TEST_PIN)
    try:
        servo.move_min()  # 转到最小角度
        time.sleep(1)
        servo.center()  # 转到中间位置
        time.sleep(1)
        servo.move_max()  # 转到最大角度
        time.sleep(1)
        servo.move_to(45, 2, 0.02)  # 平滑移动到 45 度
        time.sleep(1)
        servo.move_to(135, 2, 0.02)  # 平滑移动到 135 度

    finally:
        servo.cleanup()
