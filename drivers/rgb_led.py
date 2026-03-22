"""RGB LED driver.

Notes:
- This driver controls the three LED channels directly and does not know project states.
- For common-anode LEDs, PWM is inverted automatically.
"""

import time

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - only hit off Raspberry Pi
    GPIO = None


class RgbLed:
    """Simple driver for an RGB LED."""

    def __init__(
        self,
        red_pin: int,
        green_pin: int,
        blue_pin: int,
        common_anode: bool = True,
        frequency: int = 1000,
        gpio_module=None,
    ) -> None:
        """
        Initialize the RGB LED.

        Args:
            red_pin: BCM GPIO pin connected to the red channel.
            green_pin: BCM GPIO pin connected to the green channel.
            blue_pin: BCM GPIO pin connected to the blue channel.
            common_anode: If True, invert PWM output for a common-anode LED.
            frequency: PWM frequency in Hz.
            gpio_module: Optional GPIO-compatible module for testing or mocking.
        """
        self.red_pin = red_pin
        self.green_pin = green_pin
        self.blue_pin = blue_pin
        self.common_anode = common_anode
        self.frequency = frequency
        self._gpio = gpio_module or GPIO
        self._current_rgb = (0, 0, 0)

        if self._gpio is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install it on the Raspberry Pi or "
                "pass a compatible gpio_module for testing."
            )

        if self._gpio.getmode() is None:
            self._gpio.setmode(self._gpio.BCM)

        self._gpio.setup(self.red_pin, self._gpio.OUT)
        self._gpio.setup(self.green_pin, self._gpio.OUT)
        self._gpio.setup(self.blue_pin, self._gpio.OUT)

        self._red_pwm = self._gpio.PWM(self.red_pin, self.frequency)
        self._green_pwm = self._gpio.PWM(self.green_pin, self.frequency)
        self._blue_pwm = self._gpio.PWM(self.blue_pin, self.frequency)

        off_duty = 100 if self.common_anode else 0
        self._red_pwm.start(off_duty)
        self._green_pwm.start(off_duty)
        self._blue_pwm.start(off_duty)

    @property
    def current_rgb(self) -> tuple[int, int, int]:
        """Return the current RGB value."""
        return self._current_rgb

    def _validate_value(self, value: int, name: str) -> None:
        if not 0 <= value <= 255:
            raise ValueError(f"{name} must be between 0 and 255")

    def _to_duty_cycle(self, value: int) -> float:
        brightness = value / 255 * 100
        return 100 - brightness if self.common_anode else brightness

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        """
        Set the LED color using RGB values from 0 to 255.

        Args:
            red: Red channel brightness, from 0 to 255.
            green: Green channel brightness, from 0 to 255.
            blue: Blue channel brightness, from 0 to 255.
        """
        self._validate_value(red, "red")
        self._validate_value(green, "green")
        self._validate_value(blue, "blue")

        self._red_pwm.ChangeDutyCycle(self._to_duty_cycle(red))
        self._green_pwm.ChangeDutyCycle(self._to_duty_cycle(green))
        self._blue_pwm.ChangeDutyCycle(self._to_duty_cycle(blue))

        self._current_rgb = (red, green, blue)

    def set_color(self, color: str) -> None:
        """
        Set the LED using a simple color name.

        Args:
            color: One of "off", "red", "green", "blue", "yellow",
                "cyan", "magenta", or "white".
        """
        color_map = {
            "off": (0, 0, 0),
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "yellow": (255, 255, 0),
            "cyan": (0, 255, 255),
            "magenta": (255, 0, 255),
            "white": (255, 255, 255),
        }

        if color not in color_map:
            raise ValueError(f"Unsupported color: {color}")

        self.set_rgb(*color_map[color])

    def blink(
        self,
        color: str,
        on_time: float = 0.3,
        off_time: float = 0.3,
        repeat: int = 3,
    ) -> None:
        """
        Blink the LED with a named color.

        Args:
            color: One of the supported color names.
            on_time: Time in seconds to keep the LED on.
            off_time: Time in seconds to keep the LED off between blinks.
            repeat: Number of blink cycles.
        """
        if on_time < 0 or off_time < 0:
            raise ValueError("on_time and off_time must be >= 0")
        if repeat < 1:
            raise ValueError("repeat must be >= 1")

        for index in range(repeat):
            self.set_color(color)
            time.sleep(on_time)
            self.off()

            if index < repeat - 1:
                time.sleep(off_time)

    def off(self) -> None:
        """Turn the LED off."""
        self.set_rgb(0, 0, 0)

    def cleanup(self) -> None:
        """Turn the LED off and release the GPIO pins."""
        self.off()
        self._red_pwm.stop()
        self._green_pwm.stop()
        self._blue_pwm.stop()
        self._gpio.cleanup(self.red_pin)
        self._gpio.cleanup(self.green_pin)
        self._gpio.cleanup(self.blue_pin)

    def close(self) -> None:
        """Alias of cleanup()."""
        self.cleanup()


if __name__ == "__main__":
    TEST_RED_PIN = 5
    TEST_GREEN_PIN = 6
    TEST_BLUE_PIN = 26

    led = RgbLed(TEST_RED_PIN, TEST_GREEN_PIN, TEST_BLUE_PIN)
    try:
        led.set_color("red")
        time.sleep(1)  # 红灯亮 1 秒
        led.set_color("green")
        time.sleep(1)  # 绿灯亮 1 秒
        led.set_color("blue")
        time.sleep(1)  # 蓝灯亮 1 秒
        led.set_color("white")
        time.sleep(1)  # 白灯亮 1 秒
        led.set_rgb(255, 100, 0)
        time.sleep(1)  # 橙色亮 1 秒
        led.blink("cyan", 0.2, 0.2, 3)  # 青色闪三次
        led.off()
    finally:
        led.cleanup()
