"""Outbound email notifications for access requests."""

from __future__ import annotations

import copy
import smtplib
import threading
import time
from email.message import EmailMessage

from config import config
from services.email_settings_service import EmailSettingsService


class EmailNotificationService:
    """Send email notifications for button-triggered open requests."""

    def __init__(self, email_settings_service: EmailSettingsService, smtp_factory=smtplib.SMTP) -> None:
        self._email_settings_service = email_settings_service
        self._smtp_factory = smtp_factory
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_result: dict | None = None
        self._last_sent_at_monotonic = 0.0

    def get_status(self) -> dict:
        """Return current email notification status."""
        settings = self._email_settings_service.get_settings()
        active_scheme = next((scheme for scheme in settings["schemes"] if scheme["enabled"]), None)
        with self._lock:
            return {
                "enabled": settings["enabled"],
                "smtp_host": settings["smtp_host"],
                "smtp_port": settings["smtp_port"],
                "frontend_url": settings["frontend_url"],
                "active_scheme": None
                if active_scheme is None
                else {
                    "id": active_scheme["id"],
                    "name": active_scheme["name"],
                    "enabled": active_scheme["enabled"],
                    "username": active_scheme["username"],
                    "from_address": active_scheme["from_address"] or active_scheme["username"],
                    "to_addresses": [entry["email"] for entry in active_scheme["recipients"]],
                },
                "last_error": self._last_error,
                "last_result": copy.deepcopy(self._last_result),
            }

    def send_open_request_email(self) -> dict:
        """Send one email for a button-triggered open request."""
        return self._send_runtime_email(
            request_type="Open door request",
            request_message=config.email.request_message,
            subject=config.email.request_subject,
            bypass_cooldown=False,
        )

    def send_test_email(self, scheme_id: int | None = None) -> dict:
        """Send a one-off test email for the selected or enabled scheme."""
        subject = config.email.request_subject.strip() or "ParcelBox email test"
        return self._send_runtime_email(
            scheme_id=scheme_id,
            request_type="Email configuration test",
            request_message="This is a ParcelBox test email for the selected delivery scheme.",
            subject=f"Test: {subject}",
            bypass_cooldown=True,
        )

    def _send_runtime_email(
        self,
        *,
        request_type: str,
        request_message: str,
        subject: str,
        bypass_cooldown: bool,
        scheme_id: int | None = None,
    ) -> dict:
        now_monotonic = time.monotonic()
        if not config.email.enabled:
            result = {
                "status": "disabled",
                "reason": "email notifications disabled in config",
                "timestamp": time.time(),
            }
            with self._lock:
                self._last_result = copy.deepcopy(result)
            return result

        runtime_config = self._email_settings_service.resolve_runtime_email_config(scheme_id=scheme_id)
        if runtime_config is None:
            result = {
                "status": "disabled",
                "reason": "no enabled email subscription scheme is configured",
                "timestamp": time.time(),
            }
            with self._lock:
                self._last_result = copy.deepcopy(result)
            return result

        with self._lock:
            if not bypass_cooldown:
                cooldown = max(config.email.duplicate_request_cooldown_seconds, 0.0)
                elapsed = now_monotonic - self._last_sent_at_monotonic
                if self._last_sent_at_monotonic > 0 and elapsed < cooldown:
                    result = {
                        "status": "duplicate_filtered",
                        "reason": "recent open request email already sent",
                        "cooldown_seconds": cooldown,
                        "retry_after_seconds": round(cooldown - elapsed, 2),
                        "scheme_id": runtime_config["scheme_id"],
                        "scheme_name": runtime_config["scheme_name"],
                        "timestamp": time.time(),
                    }
                    self._last_result = copy.deepcopy(result)
                    return result

        try:
            message = self._build_message(
                runtime_config,
                request_type=request_type,
                request_message=request_message,
                subject=subject,
            )
            self._send_message(message, runtime_config)
        except Exception as error:
            result = {
                "status": "error",
                "error": str(error),
                "scheme_id": runtime_config["scheme_id"],
                "scheme_name": runtime_config["scheme_name"],
                "timestamp": time.time(),
            }
            with self._lock:
                self._last_error = str(error)
                self._last_result = copy.deepcopy(result)
            return result

        result = {
            "status": "sent",
            "subject": message["Subject"],
            "to_addresses": list(runtime_config["to_addresses"]),
            "frontend_url": runtime_config["frontend_url"],
            "scheme_id": runtime_config["scheme_id"],
            "scheme_name": runtime_config["scheme_name"],
            "timestamp": time.time(),
        }
        with self._lock:
            self._last_error = None
            self._last_result = copy.deepcopy(result)
            if not bypass_cooldown:
                self._last_sent_at_monotonic = now_monotonic
        return result

    def _build_message(
        self,
        runtime_config: dict,
        *,
        request_type: str,
        request_message: str,
        subject: str,
    ) -> EmailMessage:
        from_address = runtime_config["from_address"].strip()
        to_addresses = [address.strip() for address in runtime_config["to_addresses"] if address.strip()]
        if not from_address:
            raise RuntimeError("email from_address is not configured")
        if not to_addresses:
            raise RuntimeError("email recipients are not configured")
        if not runtime_config["smtp_host"].strip():
            raise RuntimeError("email smtp_host is not configured")

        sent_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        body = "\n".join(
            [
                request_message,
                "",
                f"Request type: {request_type}",
                f"Sent at: {sent_at}",
                f"Frontend page: {runtime_config['frontend_url']}",
                f"Delivery scheme: {runtime_config['scheme_name']}",
            ]
        )

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = from_address
        message["To"] = ", ".join(to_addresses)
        message.set_content(body)
        return message

    def _send_message(self, message: EmailMessage, runtime_config: dict) -> None:
        timeout = max(runtime_config["timeout_seconds"], 1.0)
        with self._smtp_factory(
            runtime_config["smtp_host"],
            runtime_config["smtp_port"],
            timeout=timeout,
        ) as smtp:
            if runtime_config["use_tls"]:
                smtp.starttls()
            if runtime_config["username"]:
                smtp.login(runtime_config["username"], runtime_config["password"])
            smtp.send_message(message)
