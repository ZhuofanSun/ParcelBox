from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from config import config
from data.event_store import EventStore
from services.email_service import EmailNotificationService
from services.email_settings_service import EmailSettingsService


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
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "email_settings.db"
        config.storage.database_url = f"sqlite:///{self.db_path}"
        FakeSMTP.reset()
        config.email.enabled = True
        config.email.smtp_host = "smtp.example.com"
        config.email.smtp_port = 587
        config.email.use_tls = True
        config.email.timeout_seconds = 5.0
        config.email.frontend_url = "http://locker.local:8000/"
        config.email.request_subject = "Open request"
        config.email.request_message = "Visitor requested the door to open."
        config.email.duplicate_request_cooldown_seconds = 30.0
        self.store = EventStore()
        self.store.start()
        self.settings_service = EmailSettingsService(self.store)

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
        self.store.stop()
        self.temp_dir.cleanup()

    def create_scheme(
        self,
        *,
        name: str = "Primary",
        enabled: bool = True,
        username: str = "sender@example.com",
        password: str = "secret",
        from_address: str = "parcelbox@example.com",
        recipients: list[str] | None = None,
    ) -> dict:
        return self.settings_service.create_scheme(
            name=name,
            enabled=enabled,
            username=username,
            password=password,
            from_address=from_address,
            recipients=recipients or ["frontdesk@example.com"],
        )

    def test_send_open_request_email_includes_link_and_text(self) -> None:
        self.create_scheme()
        service = EmailNotificationService(self.settings_service, smtp_factory=FakeSMTP)

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
        self.assertEqual(FakeSMTP.login_calls, [("sender@example.com", "secret")])

    def test_duplicate_request_is_filtered_within_cooldown(self) -> None:
        self.create_scheme()
        service = EmailNotificationService(self.settings_service, smtp_factory=FakeSMTP)

        first = service.send_open_request_email()
        second = service.send_open_request_email()

        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "duplicate_filtered")
        self.assertEqual(len(FakeSMTP.sent_messages), 1)

    def test_disabled_email_returns_disabled_status(self) -> None:
        config.email.enabled = False
        self.create_scheme()
        service = EmailNotificationService(self.settings_service, smtp_factory=FakeSMTP)

        result = service.send_open_request_email()

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(FakeSMTP.sent_messages, [])

    def test_send_test_email_uses_selected_scheme_even_if_not_enabled(self) -> None:
        scheme = self.create_scheme(name="Draft", enabled=False, recipients=["ops@example.com"])
        service = EmailNotificationService(self.settings_service, smtp_factory=FakeSMTP)

        result = service.send_test_email(scheme["id"])

        self.assertEqual(result["status"], "sent")
        self.assertEqual(FakeSMTP.sent_messages[0]["to"], "ops@example.com")
        self.assertEqual(FakeSMTP.sent_messages[0]["subject"], "Test: Open request")


if __name__ == "__main__":
    unittest.main()
