from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from drivers.pn532 import PN532Reader


class FakePN532Backend:
    def __init__(self, responses):
        self.firmware_version = (0x32, 0x01, 0x06, 0x07)
        self._responses = list(responses)
        self.sam_configuration_calls = 0
        self.read_calls: list[dict] = []

    def SAM_configuration(self):
        self.sam_configuration_calls += 1

    def read_passive_target(self, *, card_baud, timeout):
        self.read_calls.append({"card_baud": card_baud, "timeout": timeout})
        if not self._responses:
            return None
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class PN532ReaderTests(unittest.TestCase):
    def test_get_firmware_info_exposes_expected_shape(self) -> None:
        reader = PN532Reader(backend=FakePN532Backend([]))

        firmware = reader.get_firmware_info()

        self.assertEqual(firmware["ic"], 0x32)
        self.assertEqual(firmware["version_major"], 1)
        self.assertEqual(firmware["version_minor"], 6)
        self.assertEqual(firmware["support"], 7)

    def test_read_uid_hex_returns_uppercase_uid(self) -> None:
        reader = PN532Reader(backend=FakePN532Backend([bytearray([0xFD, 0x16, 0x50, 0x06])]))

        uid = reader.read_uid_hex(timeout=0.1, poll_interval=0.01)

        self.assertEqual(uid, "FD165006")

    def test_read_uid_number_returns_integer_value(self) -> None:
        reader = PN532Reader(backend=FakePN532Backend([bytearray([0x01, 0x23, 0x45, 0x67])]))

        uid_number = reader.read_uid_number(timeout=0.1, poll_interval=0.01)

        self.assertEqual(uid_number, 0x01234567)

    def test_wait_for_card_returns_true_when_uid_is_seen(self) -> None:
        reader = PN532Reader(backend=FakePN532Backend([bytearray([0xDE, 0xAD, 0xBE, 0xEF])]))

        detected = reader.wait_for_card(timeout=0.1, poll_interval=0.01)

        self.assertTrue(detected)

    def test_scan_target_ignores_multi_card_and_long_uid_errors(self) -> None:
        backend = FakePN532Backend(
            [
                RuntimeError("More than one card detected!"),
                RuntimeError("Found card with unexpectedly long UID!"),
                bytearray([0xAA, 0xBB, 0xCC, 0xDD]),
            ]
        )
        reader = PN532Reader(backend=backend)

        target = reader.scan_target(timeout=0.3, poll_interval=0.0 + 0.01)

        self.assertIsNotNone(target)
        self.assertEqual(target.uid_hex, "AABBCCDD")
        self.assertEqual(backend.sam_configuration_calls, 1)

    def test_scan_target_ignores_malformed_target_payloads(self) -> None:
        backend = FakePN532Backend([IndexError("short response"), bytearray([0x10, 0x20, 0x30, 0x40])])
        reader = PN532Reader(backend=backend)

        target = reader.scan_target(timeout=0.2, poll_interval=0.01)

        self.assertIsNotNone(target)
        self.assertEqual(target.uid_hex, "10203040")

    def test_scan_target_returns_none_on_timeout(self) -> None:
        reader = PN532Reader(backend=FakePN532Backend([None, None, None]))

        target = reader.scan_target(timeout=0.03, poll_interval=0.01)

        self.assertIsNone(target)


if __name__ == "__main__":
    unittest.main()
