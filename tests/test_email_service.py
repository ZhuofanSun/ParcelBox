from __future__ import annotations

import copy
import unittest

from config import config
from services.email_service import EmailNotificationService


class FakeSMTP:
    sent_messages: list[dict] = []
    starttls_calls = 0
    login_calls: list[tuple[str, str]] = []

    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def starttls(self) -> None:
        type(self).starttls_calls += 1

    def login(self, username: str, password: str) -> None:
        type(self).login_calls.append((username, password))

    def send_message(self, message) -> None:
        type(self).sent_messages.append(
            {
                "subject": message["Subject"],
                "from": message["From"],
                "to": message["To"],
                "body": message.get_content(),
            }
        )

    @classmethod
    def reset(cls) -> None:
        cls.sent_messages = []
        cls.starttls_calls = 0
        cls.login_calls = []


class EmailNotificationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = copy.deepcopy(config)
        FakeSMTP.reset()
        config.email.enabled = True
        config.email.smtp_host = "smtp.example.com"
        config.email.smtp_port = 587
        config.email.use_tls = True
        config.email.timeout_seconds = 5.0
        config.email.username = "sender@example.com"
        config.email.password = "secret"
        config.email.from_address = "parcelbox@example.com"
        config.email.to_addresses = ["frontdesk@example.com"]
        config.email.frontend_url = "http://locker.local:8000/"
        config.email.request_subject = "Open request"
        config.email.request_message = "Visitor requested the door to open."
        config.email.duplicate_request_cooldown_seconds = 30.0

    def tearDown(self) -> None:
        config.gpio = self.original_config.gpio
        config.camera = self.original_config.camera
        config.camera_mount = self.original_config.camera_mount
        config.door = self.original_config.door
        config.rfid = self.original_config.rfid
        config.ultrasonic = self.original_config.ultrasonic
        config.storage = self.original_config.storage
        config.email = self.original_config.email
        config.vision = self.original_config.vision
        config.web = self.original_config.web

    def test_send_open_request_email_includes_link_and_text(self) -> None:
        service = EmailNotificationService(smtp_factory=FakeSMTP)

        result = service.send_open_request_email()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(FakeSMTP.sent_messages), 1)
        message = FakeSMTP.sent_messages[0]
        self.assertEqual(message["subject"], "Open request")
        self.assertEqual(message["from"], "parcelbox@example.com")
        self.assertEqual(message["to"], "frontdesk@example.com")
        self.assertIn("Visitor requested the door to open.", message["body"])
        self.assertIn("Request type: Open door request", message["body"])
        self.assertIn("http://locker.local:8000/", message["body"])

    def test_duplicate_request_is_filtered_within_cooldown(self) -> None:
        service = EmailNotificationService(smtp_factory=FakeSMTP)

        first = service.send_open_request_email()
        second = service.send_open_request_email()

        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "duplicate_filtered")
        self.assertEqual(len(FakeSMTP.sent_messages), 1)

    def test_disabled_email_returns_disabled_status(self) -> None:
        config.email.enabled = False
        service = EmailNotificationService(smtp_factory=FakeSMTP)

        result = service.send_open_request_email()

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(FakeSMTP.sent_messages, [])


if __name__ == "__main__":
    unittest.main()
