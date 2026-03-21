"""Outbound email notifications for access requests."""

from __future__ import annotations

import copy
import smtplib
import threading
import time
from email.message import EmailMessage

from config import config


class EmailNotificationService:
    """Send email notifications for button-triggered open requests."""

    def __init__(self, smtp_factory=smtplib.SMTP) -> None:
        self._smtp_factory = smtp_factory
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_result: dict | None = None
        self._last_sent_at_monotonic = 0.0

    def get_status(self) -> dict:
        """Return current email notification status."""
        with self._lock:
            return {
                "enabled": config.email.enabled,
                "smtp_host": config.email.smtp_host,
                "smtp_port": config.email.smtp_port,
                "from_address": self._from_address(),
                "to_addresses": list(config.email.to_addresses),
                "frontend_url": self._frontend_url(),
                "last_error": self._last_error,
                "last_result": copy.deepcopy(self._last_result),
            }

    def send_open_request_email(self) -> dict:
        """Send one email for a button-triggered open request."""
        now_monotonic = time.monotonic()
        with self._lock:
            if not config.email.enabled:
                result = {
                    "status": "disabled",
                    "reason": "email notifications disabled in config",
                    "timestamp": time.time(),
                }
                self._last_result = copy.deepcopy(result)
                return result

            cooldown = max(config.email.duplicate_request_cooldown_seconds, 0.0)
            elapsed = now_monotonic - self._last_sent_at_monotonic
            if self._last_sent_at_monotonic > 0 and elapsed < cooldown:
                result = {
                    "status": "duplicate_filtered",
                    "reason": "recent open request email already sent",
                    "cooldown_seconds": cooldown,
                    "retry_after_seconds": round(cooldown - elapsed, 2),
                    "timestamp": time.time(),
                }
                self._last_result = copy.deepcopy(result)
                return result

        try:
            message = self._build_message()
            self._send_message(message)
        except Exception as error:
            result = {
                "status": "error",
                "error": str(error),
                "timestamp": time.time(),
            }
            with self._lock:
                self._last_error = str(error)
                self._last_result = copy.deepcopy(result)
            return result

        result = {
            "status": "sent",
            "subject": message["Subject"],
            "to_addresses": list(config.email.to_addresses),
            "frontend_url": self._frontend_url(),
            "timestamp": time.time(),
        }
        with self._lock:
            self._last_error = None
            self._last_result = copy.deepcopy(result)
            self._last_sent_at_monotonic = now_monotonic
        return result

    def _build_message(self) -> EmailMessage:
        from_address = self._from_address()
        to_addresses = [address.strip() for address in config.email.to_addresses if address.strip()]
        if not from_address:
            raise RuntimeError("email from_address is not configured")
        if not to_addresses:
            raise RuntimeError("email to_addresses is not configured")
        if not config.email.smtp_host.strip():
            raise RuntimeError("email smtp_host is not configured")

        sent_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        frontend_url = self._frontend_url()
        body = "\n".join(
            [
                config.email.request_message,
                "",
                "Request type: Open door request",
                f"Sent at: {sent_at}",
                f"Frontend page: {frontend_url}",
            ]
        )

        message = EmailMessage()
        message["Subject"] = config.email.request_subject
        message["From"] = from_address
        message["To"] = ", ".join(to_addresses)
        message.set_content(body)
        return message

    def _send_message(self, message: EmailMessage) -> None:
        timeout = max(config.email.timeout_seconds, 1.0)
        with self._smtp_factory(
            config.email.smtp_host,
            config.email.smtp_port,
            timeout=timeout,
        ) as smtp:
            if config.email.use_tls:
                smtp.starttls()
            if config.email.username.strip():
                smtp.login(config.email.username, config.email.password)
            smtp.send_message(message)

    def _from_address(self) -> str:
        configured = config.email.from_address.strip()
        if configured:
            return configured
        return config.email.username.strip()

    def _frontend_url(self) -> str:
        configured = config.email.frontend_url.strip()
        if configured:
            return configured

        host = config.web.host
        if host in {"0.0.0.0", "::"}:
            host = "192.168.0.182"
        return f"http://{host}:{config.web.port}/"
