import time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - only hit off Raspberry Pi
    GPIO = None


class UltrasonicSensor:
    """Simple driver for an ultrasonic distance sensor."""

    def __init__(
        self,
        trigger_pin: int,
        echo_pin: int,
        sound_speed_cm_s: float = 34300,
        gpio_module=None,
    ) -> None:
        """
        Initialize the ultrasonic sensor.

        Args:
            trigger_pin: BCM GPIO pin connected to the trigger pin.
            echo_pin: BCM GPIO pin connected to the echo pin.
            sound_speed_cm_s: Speed of sound in cm/s used for distance calculation.
            gpio_module: Optional GPIO-compatible module for testing or mocking.
        """
        if sound_speed_cm_s <= 0:
            raise ValueError("sound_speed_cm_s must be > 0")

        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        self.sound_speed_cm_s = sound_speed_cm_s
        self._gpio = gpio_module or GPIO

        if self._gpio is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install it on the Raspberry Pi or "
                "pass a compatible gpio_module for testing."
            )

        if self._gpio.getmode() is None:
            self._gpio.setmode(self._gpio.BCM)

        self._gpio.setup(self.trigger_pin, self._gpio.OUT, initial=self._gpio.LOW)
        self._gpio.setup(self.echo_pin, self._gpio.IN)

        time.sleep(0.05)

    def trigger(self, pulse_time: float = 0.00001) -> None:
        """
        Send a trigger pulse to the sensor.

        Args:
            pulse_time: Trigger pulse width in seconds. Most modules use 10 microseconds.
        """
        if pulse_time <= 0:
            raise ValueError("pulse_time must be > 0")

        self._gpio.output(self.trigger_pin, self._gpio.LOW)
        time.sleep(0.000002)
        self._gpio.output(self.trigger_pin, self._gpio.HIGH)
        time.sleep(pulse_time)
        self._gpio.output(self.trigger_pin, self._gpio.LOW)

    def measure_pulse(self, timeout: float = 0.03) -> float | None:
        """
        Measure the echo pulse duration in seconds.

        Args:
            timeout: Maximum wait time for the echo start and end.
        """
        if timeout <= 0:
            raise ValueError("timeout must be > 0")

        self.trigger()

        start_deadline = time.perf_counter() + timeout
        while self._gpio.input(self.echo_pin) == self._gpio.LOW:
            if time.perf_counter() > start_deadline:
                return None

        pulse_start = time.perf_counter()
        end_deadline = pulse_start + timeout

        while self._gpio.input(self.echo_pin) == self._gpio.HIGH:
            if time.perf_counter() > end_deadline:
                return None

        pulse_end = time.perf_counter()
        return pulse_end - pulse_start

    def measure_distance_cm(self, samples: int = 3, sample_interval: float = 0.05, timeout: float = 0.03):
        """
        Measure distance in centimeters.

        Args:
            samples: Number of samples to collect. The median value is returned.
            sample_interval: Delay between samples, in seconds.
            timeout: Maximum wait time for each echo pulse.
        """
        if samples < 1:
            raise ValueError("samples must be >= 1")
        if sample_interval < 0:
            raise ValueError("sample_interval must be >= 0")

        distances = []

        for index in range(samples):
            pulse_duration = self.measure_pulse(timeout)
            if pulse_duration is not None:
                distance_cm = pulse_duration * self.sound_speed_cm_s / 2
                distances.append(distance_cm)

            if index < samples - 1:
                time.sleep(sample_interval)

        if not distances:
            return None

        distances.sort()
        return distances[len(distances) // 2]

    def measure_distance_m(self, samples: int = 3, sample_interval: float = 0.05, timeout: float = 0.03):
        """
        Measure distance in meters.

        Args:
            samples: Number of samples to collect. The median value is returned.
            sample_interval: Delay between samples, in seconds.
            timeout: Maximum wait time for each echo pulse.
        """
        distance_cm = self.measure_distance_cm(samples, sample_interval, timeout)
        if distance_cm is None:
            return None

        return distance_cm / 100

    def cleanup(self) -> None:
        """Release the GPIO pins."""
        self._gpio.output(self.trigger_pin, self._gpio.LOW)
        self._gpio.cleanup(self.trigger_pin)
        self._gpio.cleanup(self.echo_pin)

    def close(self) -> None:
        """Alias of cleanup()."""
        self.cleanup()


if __name__ == "__main__":
    TEST_TRIGGER_PIN = 16
    TEST_ECHO_PIN = 20

    sensor = UltrasonicSensor(TEST_TRIGGER_PIN, TEST_ECHO_PIN)
    try:
        print("Measuring distance...")
        while True:
            distance_cm = sensor.measure_distance_cm()
            if distance_cm is None:
                print("No echo")
            else:
                print(f"Distance: {distance_cm:.2f} cm")  # 持续打印测到的厘米距离
            time.sleep(0.3)
    finally:
        sensor.cleanup()
