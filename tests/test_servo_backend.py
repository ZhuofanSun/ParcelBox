from __future__ import annotations

import unittest

from drivers.servo import Servo


class FakePigpioClient:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.mode_calls: list[tuple[int, str]] = []
        self.pulsewidth_calls: list[tuple[int, int]] = []
        self.stopped = False

    def set_mode(self, pin: int, mode) -> None:
        self.mode_calls.append((pin, mode))

    def set_servo_pulsewidth(self, pin: int, pulsewidth: int) -> None:
        self.pulsewidth_calls.append((pin, pulsewidth))

    def stop(self) -> None:
        self.stopped = True


class FakePigpioModule:
    OUTPUT = "output"

    def __init__(self, *, connected: bool = True) -> None:
        self.client = FakePigpioClient(connected=connected)

    def pi(self) -> FakePigpioClient:
        return self.client


class FakePwm:
    def __init__(self, pin: int, frequency: int) -> None:
        self.pin = pin
        self.frequency = frequency
        self.started_with = None
        self.duty_cycles: list[float] = []
        self.stopped = False

    def start(self, duty_cycle: float) -> None:
        self.started_with = duty_cycle

    def ChangeDutyCycle(self, duty_cycle: float) -> None:
        self.duty_cycles.append(duty_cycle)

    def stop(self) -> None:
        self.stopped = True


class FakeGpioModule:
    BCM = "bcm"
    OUT = "out"

    def __init__(self) -> None:
        self._mode = None
        self.setup_calls: list[tuple[int, str]] = []
        self.cleanup_calls: list[int] = []
        self.pwm_instances: list[FakePwm] = []

    def getmode(self):
        return self._mode

    def setmode(self, mode) -> None:
        self._mode = mode

    def setup(self, pin: int, mode) -> None:
        self.setup_calls.append((pin, mode))

    def PWM(self, pin: int, frequency: int) -> FakePwm:
        pwm = FakePwm(pin, frequency)
        self.pwm_instances.append(pwm)
        return pwm

    def cleanup(self, pin: int) -> None:
        self.cleanup_calls.append(pin)


class ServoBackendTests(unittest.TestCase):
    def test_prefers_pigpio_backend_when_available(self) -> None:
        pigpio_module = FakePigpioModule(connected=True)
        gpio_module = FakeGpioModule()

        servo = Servo(13, pigpio_module=pigpio_module, gpio_module=gpio_module)
        servo.set_angle(90, settle_time=0, release=False)
        servo.release()
        servo.cleanup()

        self.assertEqual(servo.backend_name, "pigpio")
        self.assertEqual(pigpio_module.client.mode_calls[0], (13, pigpio_module.OUTPUT))
        self.assertIn((13, 1500), pigpio_module.client.pulsewidth_calls)
        self.assertEqual(pigpio_module.client.pulsewidth_calls[-1], (13, 0))
        self.assertTrue(pigpio_module.client.stopped)
        self.assertEqual(gpio_module.pwm_instances, [])

    def test_falls_back_to_rpi_gpio_when_pigpio_is_unavailable(self) -> None:
        pigpio_module = FakePigpioModule(connected=False)
        gpio_module = FakeGpioModule()

        servo = Servo(12, pigpio_module=pigpio_module, gpio_module=gpio_module)
        servo.set_angle(90, settle_time=0, release=False)
        servo.release()
        servo.cleanup()

        self.assertEqual(servo.backend_name, "rpi_gpio")
        self.assertEqual(gpio_module.setup_calls[0], (12, gpio_module.OUT))
        self.assertEqual(len(gpio_module.pwm_instances), 1)
        self.assertAlmostEqual(gpio_module.pwm_instances[0].duty_cycles[0], 7.5, places=2)
        self.assertEqual(gpio_module.pwm_instances[0].duty_cycles[-1], 0)
        self.assertEqual(gpio_module.cleanup_calls, [12])

    def test_forced_pigpio_backend_raises_when_daemon_is_unavailable(self) -> None:
        pigpio_module = FakePigpioModule(connected=False)

        with self.assertRaises(RuntimeError):
            Servo(18, backend="pigpio", pigpio_module=pigpio_module, gpio_module=FakeGpioModule())


if __name__ == "__main__":
    unittest.main()
