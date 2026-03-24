"""Simple hardware smoke tests driven by config.py."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import config
from drivers.button import Button
from drivers.buzzer import Buzzer
from drivers.camera import CsiCamera
from drivers.pn532 import PN532Reader
from drivers.rgb_led import RgbLed
from drivers.servo import Servo
from drivers.ultrasonic_sensor import UltrasonicSensor


def smoke_button(duration: float | None = None) -> None:
    button = Button(config.gpio.button_pin)
    try:
        if duration is None:
            print("Watching button state. Press Ctrl+C to stop.")
        else:
            print(f"Watching button state for {duration:.0f} seconds...")

        deadline = None if duration is None else time.time() + duration
        last_state = button.is_pressed
        print("Pressed" if last_state else "Released")

        while deadline is None or time.time() < deadline:
            current_state = button.is_pressed
            if current_state != last_state:
                print("Pressed" if current_state else "Released")
                last_state = current_state
            time.sleep(0.02)
    finally:
        button.cleanup()


def smoke_buzzer() -> None:
    buzzer = Buzzer(config.gpio.buzzer_pin)
    try:
        print("Playing buzzer smoke test...")
        buzzer.beep(0.1, 2, 0.1)
        time.sleep(0.3)
        buzzer.beep_pattern([0.1, 0.1, 0.3], 0.1)
    finally:
        buzzer.cleanup()


def smoke_servo(pin: int, name: str) -> None:
    servo = Servo(pin)
    try:
        print(f"Testing {name} on GPIO{pin}...")
        servo.center()
        time.sleep(0.5)
        servo.move_to(60, 2, 0.02)
        time.sleep(0.5)
        servo.move_to(120, 2, 0.02)
        time.sleep(0.5)
        servo.center()
    finally:
        servo.cleanup()


def smoke_rgb() -> None:
    led = RgbLed(
        config.gpio.rgb_red_pin,
        config.gpio.rgb_green_pin,
        config.gpio.rgb_blue_pin,
    )
    try:
        print("Cycling RGB LED...")
        for color in ["red", "green", "blue", "white", "yellow", "cyan"]:
            print("Color:", color)
            led.set_color(color)
            time.sleep(0.5)

        led.blink("magenta", 0.2, 0.2, 3)
        led.off()
    finally:
        led.cleanup()


def smoke_ultrasonic(duration: float | None = None) -> None:
    sensor = UltrasonicSensor(
        config.gpio.ultrasonic_trigger_pin,
        config.gpio.ultrasonic_echo_pin,
    )
    try:
        if duration is None:
            print("Printing ultrasonic distance. Press Ctrl+C to stop.")
        else:
            print(f"Printing ultrasonic distance for {duration:.0f} seconds...")

        deadline = None if duration is None else time.time() + duration

        while deadline is None or time.time() < deadline:
            distance = sensor.measure_distance_cm(
                samples=config.ultrasonic.sample_count,
                sample_interval=config.ultrasonic.sample_interval,
                method="average",
            )
            if distance is None:
                print("No echo")
            else:
                print(f"Distance: {distance:.2f} cm")
            time.sleep(0.3)
    finally:
        sensor.cleanup()


def smoke_camera() -> None:
    camera = CsiCamera(config.camera.camera_index)
    output_dir = ROOT / config.storage.snapshot_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "camera_smoke_test.jpg"

    try:
        print("Starting camera smoke test...")
        camera.configure_video(
            stream_size=config.camera.stream_size,
            detection_size=config.camera.detection_size,
            stream_format=config.camera.pixel_format,
            detection_format="YUV420",
            buffer_count=config.camera.buffer_count,
        )
        camera.start()
        camera.warmup(2)

        main_frame = camera.capture_stream_frame()
        detection_frame = camera.capture_detection_frame()
        metadata = camera.capture_metadata()

        print("Main frame shape:", main_frame.shape)
        print("Detection frame shape:", detection_frame.shape)
        print("Metadata keys:", list(metadata.keys())[:10])

        camera.capture_file(str(output_path))
        print("Saved snapshot:", output_path)
    finally:
        camera.cleanup()


def smoke_pn532(timeout: float | None = None, scans: int = 3) -> None:
    reader = PN532Reader()
    try:
        firmware = reader.get_firmware_info()
        print(
            "Found PN532: "
            f"IC=0x{firmware['ic']:02X}, "
            f"firmware={firmware['version_major']}.{firmware['version_minor']}, "
            f"support=0x{firmware['support']:02X}"
        )

        resolved_timeout = 10.0 if timeout is None else float(timeout)
        resolved_scans = max(int(scans), 1)
        followup_timeout = min(max(resolved_timeout, 0.1), 1.0)
        print(
            f"Scanning for up to {resolved_scans} compatible RFID/NFC target(s), "
            f"{resolved_timeout:.0f}s each..."
        )
        print("Unsupported or unusual targets are ignored during polling.")

        try:
            for index in range(resolved_scans):
                if not reader.wait_for_card(timeout=resolved_timeout):
                    print(f"[{index + 1}/{resolved_scans}] No compatible target detected")
                    continue
                print(f"[{index + 1}/{resolved_scans}] Compatible target detected. Hold it steady...")
                target = reader.scan_target(timeout=followup_timeout, poll_interval=0.05)
                uid_hex = reader.read_uid_hex(timeout=followup_timeout, poll_interval=0.05)
                uid_number = reader.read_uid_number(timeout=followup_timeout, poll_interval=0.05)
                print(
                    f"[{index + 1}/{resolved_scans}] "
                    f"Protocol={target.protocol if target is not None else 'unavailable'} "
                    f"UID={uid_hex if uid_hex is not None else 'unavailable'} "
                    f"Number={uid_number if uid_number is not None else 'unavailable'}"
                )
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
    finally:
        reader.cleanup()


def run_step(name: str, func) -> None:
    print(f"\n=== {name} ===")
    func()


def smoke_all() -> None:
    print("Running all hardware smoke tests...")
    print("Button and PN532 are time-limited in this mode.")

    run_step("Buzzer", smoke_buzzer)
    run_step("RGB LED", smoke_rgb)
    run_step("Door Servo", lambda: smoke_servo(config.gpio.door_servo_pin, "door servo"))
    run_step(
        "Camera Pan Servo",
        lambda: smoke_servo(config.gpio.camera_pan_servo_pin, "camera pan servo"),
    )
    run_step(
        "Camera Tilt Servo",
        lambda: smoke_servo(config.gpio.camera_tilt_servo_pin, "camera tilt servo"),
    )
    run_step("Ultrasonic Sensor", lambda: smoke_ultrasonic(8))
    run_step("Camera", smoke_camera)
    run_step("PN532", lambda: smoke_pn532(10))
    run_step("Button", lambda: smoke_button(8))
    print("\nAll hardware smoke tests finished.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run hardware smoke tests.")
    parser.add_argument(
        "device",
        nargs="?",
        default="all",
        choices=[
            "all",
            "button",
            "buzzer",
            "door-servo",
            "camera-pan-servo",
            "camera-tilt-servo",
            "rgb",
            "ultrasonic",
            "camera",
            "pn532",
        ],
        help="Hardware target to test.",
    )
    args = parser.parse_args()

    if args.device == "all":  # 有定时打断，不传参数默认跑 all
        smoke_all()
        return
    if args.device == "button":
        smoke_button()
        return
    if args.device == "buzzer":
        smoke_buzzer()
        return
    if args.device == "door-servo":
        smoke_servo(config.gpio.door_servo_pin, "door servo")
        return
    if args.device == "camera-pan-servo":
        smoke_servo(config.gpio.camera_pan_servo_pin, "camera pan servo")
        return
    if args.device == "camera-tilt-servo":
        smoke_servo(config.gpio.camera_tilt_servo_pin, "camera tilt servo")
        return
    if args.device == "rgb":
        smoke_rgb()
        return
    if args.device == "ultrasonic":
        smoke_ultrasonic()
        return
    if args.device == "camera":
        smoke_camera()
        return
    if args.device == "pn532":
        smoke_pn532()
        return

    raise RuntimeError(f"Unsupported device: {args.device}")


if __name__ == "__main__":
    main()
