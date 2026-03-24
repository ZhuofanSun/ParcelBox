"""Project wrapper around the PN532 reader.

This driver intentionally focuses on UID-based card detection. Card-content
reads and writes are excluded because the current ParcelBox flow only needs a
stable UID to identify a card in the backend.

The wrapper is defensive during polling:
- unsupported or oddly formatted targets are ignored instead of bubbling up
- multiple targets in the field are treated as "no valid card this cycle"
- unknown card technologies do not break the caller's polling loop
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

try:
    import board
    import busio
    from digitalio import DigitalInOut
except ImportError:  # pragma: no cover - only hit off Raspberry Pi
    board = None
    busio = None
    DigitalInOut = None

try:
    from adafruit_pn532.adafruit_pn532 import BusyError
    from adafruit_pn532.i2c import PN532_I2C
except ImportError:  # pragma: no cover - only hit when PN532 stack is missing
    BusyError = None
    PN532_I2C = None


CARD_BAUD_ISO14443A = 0x00


@dataclass(frozen=True)
class PN532Target:
    """One compatible target detected by the PN532 wrapper."""

    protocol: str
    uid_bytes: bytes

    @property
    def uid_hex(self) -> str:
        return "".join(f"{byte:02X}" for byte in self.uid_bytes)

    @property
    def uid_number(self) -> int:
        value = 0
        for byte in self.uid_bytes:
            value = (value << 8) | byte
        return value


class PN532Reader:
    """UID-focused PN532 reader for the ParcelBox project.

    The current implementation intentionally scans ISO14443A targets only.
    Unsupported targets are ignored during polling instead of breaking the loop.
    """

    def __init__(
        self,
        *,
        reset_pin=None,
        req_pin=None,
        debug: bool = False,
        backend=None,
        i2c_factory=None,
        pn532_class=None,
        digital_in_out_class=None,
    ) -> None:
        self._managed_resources: list[object] = []
        self._backend = backend
        self._sam_configured = False

        if self._backend is None:
            if board is None or busio is None or DigitalInOut is None:
                raise RuntimeError(
                    "Adafruit Blinka is not available. Install dependencies for "
                    "board, busio, and digitalio on the Raspberry Pi."
                )
            if PN532_I2C is None:
                raise RuntimeError(
                    "Adafruit PN532 library is not available. Install the PN532 "
                    "Python dependencies or keep the vendored library importable."
                )

            i2c_constructor = i2c_factory or busio.I2C
            pn532_constructor = pn532_class or PN532_I2C
            dio_constructor = digital_in_out_class or DigitalInOut

            reset_resource = self._build_digital_resource(reset_pin, dio_constructor)
            req_resource = self._build_digital_resource(req_pin, dio_constructor)
            if reset_resource is not None:
                self._managed_resources.append(reset_resource)
            if req_resource is not None:
                self._managed_resources.append(req_resource)
            self._i2c = i2c_constructor(board.SCL, board.SDA)
            self._managed_resources.append(self._i2c)
            self._backend = pn532_constructor(
                self._i2c,
                debug=debug,
                reset=reset_resource,
                req=req_resource,
            )

        self._ensure_sam_configuration()

    @staticmethod
    def _build_digital_resource(pin, digital_in_out_class):
        if pin is None:
            return None
        if isinstance(pin, str):
            if board is None or not hasattr(board, pin):
                raise ValueError(f"Unknown board pin: {pin}")
            pin = getattr(board, pin)
        resource = digital_in_out_class(pin)
        return resource

    def _ensure_sam_configuration(self) -> None:
        if self._sam_configured:
            return
        self._backend.SAM_configuration()
        self._sam_configured = True

    def get_firmware_info(self) -> dict:
        ic, ver, rev, support = self._backend.firmware_version
        return {
            "ic": int(ic),
            "version_major": int(ver),
            "version_minor": int(rev),
            "support": int(support),
        }

    def wait_for_card(self, timeout: float | None = None, poll_interval: float = 0.1) -> bool:
        return self.scan_target(timeout=timeout, poll_interval=poll_interval) is not None

    def scan_target(
        self,
        *,
        timeout: float | None = None,
        poll_interval: float = 0.1,
    ) -> PN532Target | None:
        """Return one compatible target, or None when nothing usable is found."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be >= 0 or None")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")

        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            remaining = None if deadline is None else max(deadline - time.monotonic(), 0.0)
            if remaining is not None and remaining <= 0:
                return None

            attempt_timeout = 0.2 if remaining is None else min(max(remaining, 0.01), 0.2)

            try:
                uid = self._backend.read_passive_target(
                    card_baud=CARD_BAUD_ISO14443A,
                    timeout=attempt_timeout,
                )
            except Exception as error:  # pragma: no cover - hardware/runtime dependent
                if self._is_ignorable_scan_error(error):
                    uid = None
                else:
                    raise

            if uid:
                uid_bytes = bytes(uid)
                if uid_bytes:
                    return PN532Target(protocol="iso14443a", uid_bytes=uid_bytes)

            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(poll_interval)

    def read_uid_hex(self, timeout: float | None = None, poll_interval: float = 0.1) -> str | None:
        target = self.scan_target(timeout=timeout, poll_interval=poll_interval)
        return None if target is None else target.uid_hex

    def read_uid_number(self, timeout: float | None = None, poll_interval: float = 0.1) -> int | None:
        target = self.scan_target(timeout=timeout, poll_interval=poll_interval)
        return None if target is None else target.uid_number

    @staticmethod
    def _is_ignorable_scan_error(error: Exception) -> bool:
        if isinstance(error, IndexError):
            # Malformed target payloads can show up when something answers the
            # poll but does not match the UID shape this project understands.
            return True
        if BusyError is not None and isinstance(error, BusyError):
            return True
        if isinstance(error, RuntimeError):
            message = str(error).lower()
            ignorable_fragments = (
                "more than one card detected",
                "unexpectedly long uid",
            )
            return any(fragment in message for fragment in ignorable_fragments)
        return False

    def cleanup(self) -> None:
        for resource in reversed(self._managed_resources):
            cleanup = getattr(resource, "deinit", None) or getattr(resource, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass
        self._managed_resources.clear()

    def close(self) -> None:
        self.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small PN532 UID-only demo.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout per scan, in seconds.")
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="How many compatible targets to scan before exiting.",
    )
    parser.add_argument(
        "--reset-pin",
        type=str,
        default=None,
        help='Optional Blinka pin name for RSTPD_N, for example "D6".',
    )
    parser.add_argument(
        "--req-pin",
        type=str,
        default=None,
        help='Optional Blinka pin name for P32/H_Request, for example "D12".',
    )
    args = parser.parse_args()

    reader = PN532Reader(reset_pin=args.reset_pin, req_pin=args.req_pin)
    try:
        firmware = reader.get_firmware_info()
        print(
            "Found PN532: "
            f"IC=0x{firmware['ic']:02X}, "
            f"firmware={firmware['version_major']}.{firmware['version_minor']}, "
            f"support=0x{firmware['support']:02X}"
        )

        print("UID-only demo mode. Unsupported or unusual targets are ignored.")
        followup_timeout = min(max(args.timeout, 0.1), 1.0)
        try:
            for index in range(max(args.count, 0)):
                print(f"\n[{index + 1}/{args.count}] Present one card or tag...")
                if not reader.wait_for_card(timeout=args.timeout):
                    print("No compatible target detected within timeout.")
                    continue

                print("Compatible target detected. Keep it near the antenna for follow-up reads.")
                target = reader.scan_target(timeout=followup_timeout, poll_interval=0.05)
                uid_hex = reader.read_uid_hex(timeout=followup_timeout, poll_interval=0.05)
                uid_number = reader.read_uid_number(timeout=followup_timeout, poll_interval=0.05)

                if target is not None:
                    print(f"Protocol: {target.protocol}")
                else:
                    print("Protocol: unavailable")

                print(f"UID (hex): {uid_hex if uid_hex is not None else 'unavailable'}")
                print(
                    "UID (number): "
                    f"{uid_number if uid_number is not None else 'unavailable'}"
                )
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
    finally:
        reader.cleanup()


if __name__ == "__main__":
    main()
