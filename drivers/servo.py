"""Standard servo driver with hardware-timed pigpio support.

Notes:
- `pigpio` is preferred because it uses hardware-timed pulses and is much more
  stable than `RPi.GPIO.PWM` under CPU load.
- The driver falls back to `RPi.GPIO` software PWM when pigpio is unavailable.
- Calibrate angle range and pulse range on the real servo before using the end points.
- Use an external 5V supply for the servo and keep grounds shared with the Pi.
"""

from __future__ import annotations

import time

try:
    import pigpio
except ImportError:  # pragma: no cover - optional dependency on Raspberry Pi
    pigpio = None

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - optional dependency on Raspberry Pi
    GPIO = None


class _PigpioServoBackend:
    """Drive a servo through pigpio's hardware-timed servo pulses."""

    backend_name = "pigpio"

    def __init__(self, pin: int, *, pigpio_module=None) -> None:
        module = pigpio_module or pigpio
        if module is None:
            raise RuntimeError("pigpio is not available")

        client = module.pi()
        if client is None or not getattr(client, "connected", False):
            if client is not None and hasattr(client, "stop"):
                client.stop()
            raise RuntimeError("pigpio daemon is unavailable")

        self.pin = pin
        self._module = module
        self._client = client
        self._client.set_mode(self.pin, self._module.OUTPUT)

    def write_pulse_width_ms(self, pulse_width_ms: float) -> None:
        self._client.set_servo_pulsewidth(self.pin, int(round(pulse_width_ms * 1000)))

    def release(self) -> None:
        self._client.set_servo_pulsewidth(self.pin, 0)

    def cleanup(self) -> None:
        try:
            self.release()
        finally:
            self._client.stop()


class _RpiGpioServoBackend:
    """Drive a servo through RPi.GPIO software PWM."""

    backend_name = "rpi_gpio"

    def __init__(self, pin: int, *, frequency: int, gpio_module=None) -> None:
        module = gpio_module or GPIO
        if module is None:
            raise RuntimeError("RPi.GPIO is not available")

        self.pin = pin
        self._gpio = module
        self._frequency = frequency

        if self._gpio.getmode() is None:
            self._gpio.setmode(self._gpio.BCM)

        self._gpio.setup(self.pin, self._gpio.OUT)
        self._pwm = self._gpio.PWM(self.pin, self._frequency)
        self._pwm.start(0)

    def write_pulse_width_ms(self, pulse_width_ms: float) -> None:
        period_ms = 1000 / self._frequency
        duty_cycle = pulse_width_ms / period_ms * 100
        self._pwm.ChangeDutyCycle(duty_cycle)

    def release(self) -> None:
        self._pwm.ChangeDutyCycle(0)

    def cleanup(self) -> None:
        self.release()
        self._pwm.stop()
        self._gpio.cleanup(self.pin)


class Servo:
    """Simple driver for a standard servo motor."""

    def __init__(
        self,
        pin: int,
        min_angle: float = 0,
        max_angle: float = 180,
        min_pulse_width: float = 0.5,
        max_pulse_width: float = 2.5,
        frequency: int = 50,
        backend: str = "auto",
        gpio_module=None,
        pigpio_module=None,
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
            backend: "auto", "pigpio", or "rpi_gpio".
            gpio_module: Optional GPIO-compatible module for testing or mocking.
            pigpio_module: Optional pigpio-compatible module for testing or mocking.
        """
        if min_angle >= max_angle:
            raise ValueError("min_angle must be smaller than max_angle")
        if min_pulse_width <= 0 or max_pulse_width <= 0:
            raise ValueError("pulse widths must be > 0")
        if min_pulse_width >= max_pulse_width:
            raise ValueError("min_pulse_width must be smaller than max_pulse_width")
        if frequency <= 0:
            raise ValueError("frequency must be > 0")

        normalized_backend = str(backend).strip().lower()
        if normalized_backend not in {"auto", "pigpio", "rpi_gpio"}:
            raise ValueError("backend must be one of: auto, pigpio, rpi_gpio")

        self.pin = pin
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.min_pulse_width = min_pulse_width
        self.max_pulse_width = max_pulse_width
        self.frequency = frequency
        self._current_angle = None
        self._backend = self._build_backend(
            normalized_backend,
            gpio_module=gpio_module,
            pigpio_module=pigpio_module,
        )

    @property
    def current_angle(self):
        """Return the last angle sent to the servo."""
        return self._current_angle

    @property
    def backend_name(self) -> str:
        """Return the active PWM backend name."""
        return self._backend.backend_name

    def _build_backend(self, backend: str, *, gpio_module=None, pigpio_module=None):
        if backend == "pigpio":
            return _PigpioServoBackend(self.pin, pigpio_module=pigpio_module)

        if backend == "rpi_gpio":
            return _RpiGpioServoBackend(self.pin, frequency=self.frequency, gpio_module=gpio_module)

        pigpio_error = None
        try:
            return _PigpioServoBackend(self.pin, pigpio_module=pigpio_module)
        except Exception as error:
            pigpio_error = error

        try:
            return _RpiGpioServoBackend(self.pin, frequency=self.frequency, gpio_module=gpio_module)
        except Exception as error:
            raise RuntimeError(
                "No usable servo backend is available. "
                f"pigpio failed with: {pigpio_error}; "
                f"RPi.GPIO failed with: {error}"
            ) from error

    def _validate_angle(self, angle: float) -> None:
        if not self.min_angle <= angle <= self.max_angle:
            raise ValueError(
                f"angle must be between {self.min_angle} and {self.max_angle}"
            )

    def _angle_to_pulse_width(self, angle: float) -> float:
        angle_range = self.max_angle - self.min_angle
        pulse_range = self.max_pulse_width - self.min_pulse_width
        return self.min_pulse_width + ((angle - self.min_angle) / angle_range) * pulse_range

    def release(self) -> None:
        """Stop sending PWM to reduce jitter after moving."""
        self._backend.release()

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
        self._backend.write_pulse_width_ms(pulse_width)
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

    def move_by(self, delta: float, settle_time: float = 0.2, release: bool = True) -> float:
        """
        Move the servo by a relative angle delta.

        Args:
            delta: Relative angle to add to the current angle.
            settle_time: Time in seconds to wait after the move.
            release: If True, stop PWM after the move to reduce jitter.
        """
        if self._current_angle is None:
            current = (self.min_angle + self.max_angle) / 2
        else:
            current = self._current_angle

        target = current + delta
        self.set_angle(target, settle_time, release)
        return target

    def sweep(
        self,
        start_angle: float,
        end_angle: float,
        step: float = 2,
        delay: float = 0.02,
        release: bool = True,
    ) -> None:
        """
        Sweep the servo from one angle to another.

        Args:
            start_angle: Sweep start angle.
            end_angle: Sweep end angle.
            step: Angle step used for each small move.
            delay: Delay in seconds between steps.
            release: If True, stop PWM after the sweep to reduce jitter.
        """
        self.set_angle(start_angle, 0.2, False)
        self.move_to(end_angle, step, delay, release)

    def cleanup(self) -> None:
        """Stop PWM and release the GPIO resources."""
        self._backend.cleanup()

    def close(self) -> None:
        """Alias of cleanup()."""
        self.cleanup()


if __name__ == "__main__":
    TEST_PIN = 13

    servo = Servo(TEST_PIN)
    try:
        print(f"Servo backend: {servo.backend_name}")
        servo.move_min()
        time.sleep(1)
        servo.center()
        time.sleep(1)
        servo.move_max(settle_time=1.0, release=False)
        time.sleep(1)
        servo.move_to(45, 2, 0.02)
        time.sleep(1)
        servo.move_to(180, 2, 0.02)
        time.sleep(1)
        servo.sweep(45, 120, 2, 0.02)
        servo.center()
        servo.move_to(120, 1, 0.02)
    finally:
        servo.cleanup()
