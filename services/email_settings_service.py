"""Device-level email subscription schemes and runtime resolution."""

from __future__ import annotations

import socket
from email.utils import parseaddr

from config import config
from data.event_store import EventStore


class EmailSettingsService:
    """Persist editable email delivery schemes while keeping SMTP host config static."""

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store

    def get_settings(self) -> dict:
        """Return the fixed SMTP config summary plus stored schemes."""
        schemes = self._event_store.list_email_subscription_schemes()
        active_scheme_id = next((scheme["id"] for scheme in schemes if scheme["enabled"]), None)
        return {
            "enabled": config.email.enabled,
            "smtp_host": config.email.smtp_host,
            "smtp_port": config.email.smtp_port,
            "use_tls": config.email.use_tls,
            "timeout_seconds": config.email.timeout_seconds,
            "frontend_url": self._frontend_url(),
            "request_subject": config.email.request_subject,
            "request_message": config.email.request_message,
            "duplicate_request_cooldown_seconds": config.email.duplicate_request_cooldown_seconds,
            "schemes": schemes,
            "active_scheme_id": active_scheme_id,
        }

    def create_scheme(
        self,
        *,
        name: str,
        enabled: bool,
        username: str,
        password: str,
        from_address: str,
        recipients: list[str],
    ) -> dict:
        """Create a new stored email scheme."""
        normalized = self._normalize_scheme_input(
            name=name,
            enabled=enabled,
            username=username,
            password=password,
            from_address=from_address,
            recipients=recipients,
        )
        self._ensure_unique_scheme_name(normalized["name"])
        scheme = self._event_store.create_email_subscription_scheme(**normalized)
        if scheme is None:
            raise ValueError(self._event_store.get_status().get("last_error") or "Failed to create email scheme")
        return scheme

    def update_scheme(
        self,
        scheme_id: int,
        *,
        name: str,
        enabled: bool,
        username: str,
        password: str,
        from_address: str,
        recipients: list[str],
    ) -> dict:
        """Overwrite an existing stored email scheme."""
        existing = self._event_store.get_email_subscription_scheme(int(scheme_id))
        if existing is None:
            raise LookupError("Email scheme not found")

        normalized = self._normalize_scheme_input(
            name=name,
            enabled=enabled,
            username=username,
            password=password,
            from_address=from_address,
            recipients=recipients,
        )
        self._ensure_unique_scheme_name(normalized["name"], exclude_scheme_id=int(scheme_id))
        scheme = self._event_store.update_email_subscription_scheme(int(scheme_id), **normalized)
        if scheme is None:
            raise ValueError(self._event_store.get_status().get("last_error") or "Failed to update email scheme")
        return scheme

    def delete_scheme(self, scheme_id: int) -> None:
        """Delete one stored email scheme."""
        deleted = self._event_store.delete_email_subscription_scheme(int(scheme_id))
        if not deleted:
            raise LookupError("Email scheme not found")

    def resolve_runtime_email_config(self, scheme_id: int | None = None) -> dict | None:
        """Merge static SMTP settings with the selected or active stored scheme."""
        if not config.email.enabled:
            return None

        if scheme_id is None:
            scheme = self._event_store.get_active_email_subscription_scheme()
            if scheme is None or not scheme["enabled"]:
                return None
        else:
            scheme = self._event_store.get_email_subscription_scheme(int(scheme_id))
        if scheme is None:
            return None

        recipients = [entry["email"] for entry in scheme["recipients"] if entry["email"].strip()]
        from_address = scheme["from_address"].strip() or scheme["username"].strip()
        return {
            "scheme_id": scheme["id"],
            "scheme_name": scheme["name"],
            "username": scheme["username"].strip(),
            "password": scheme["password"],
            "from_address": from_address,
            "to_addresses": recipients,
            "smtp_host": config.email.smtp_host,
            "smtp_port": config.email.smtp_port,
            "use_tls": config.email.use_tls,
            "timeout_seconds": config.email.timeout_seconds,
            "frontend_url": self._frontend_url(),
            "request_subject": config.email.request_subject,
            "request_message": config.email.request_message,
            "duplicate_request_cooldown_seconds": config.email.duplicate_request_cooldown_seconds,
            "enabled": config.email.enabled,
        }

    def _normalize_scheme_input(
        self,
        *,
        name: str,
        enabled: bool,
        username: str,
        password: str,
        from_address: str,
        recipients: list[str],
    ) -> dict:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("Scheme name is required")

        normalized_username = str(username or "").strip()
        normalized_password = str(password or "")
        normalized_from_address = str(from_address or "").strip()
        normalized_recipients = self._normalize_recipient_list(recipients)

        if normalized_from_address and not self._is_valid_email(normalized_from_address):
            raise ValueError("From address is not a valid email address")

        return {
            "name": normalized_name,
            "enabled": bool(enabled),
            "username": normalized_username,
            "password": normalized_password,
            "from_address": normalized_from_address,
            "recipients": normalized_recipients,
        }

    def _normalize_recipient_list(self, recipients: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for raw_email in recipients:
            email = str(raw_email or "").strip().lower()
            if not email:
                continue
            if not self._is_valid_email(email):
                raise ValueError(f"Recipient email is invalid: {raw_email}")
            if email in seen:
                continue
            deduped.append(email)
            seen.add(email)
        return deduped

    def _ensure_unique_scheme_name(self, name: str, exclude_scheme_id: int | None = None) -> None:
        for scheme in self._event_store.list_email_subscription_schemes():
            if exclude_scheme_id is not None and int(scheme["id"]) == int(exclude_scheme_id):
                continue
            if scheme["name"].strip().lower() == name.strip().lower():
                raise ValueError("An email scheme with that name already exists")

    @staticmethod
    def _is_valid_email(value: str) -> bool:
        _, parsed = parseaddr(value)
        return bool(parsed) and "@" in parsed and "." in parsed.rsplit("@", 1)[-1]

    @staticmethod
    def _frontend_url() -> str:
        configured = config.email.frontend_url.strip()
        if configured:
            return configured

        host = config.web.host
        if host not in {"0.0.0.0", "::", "127.0.0.1", "localhost"}:
            return f"http://{host}:{config.web.port}/"

        host = EmailSettingsService._discover_lan_ip() or "127.0.0.1"
        return f"http://{host}:{config.web.port}/"

    @staticmethod
    def _discover_lan_ip() -> str | None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("10.255.255.255", 1))
                candidate = probe.getsockname()[0]
                if candidate and not candidate.startswith("127."):
                    return candidate
        except OSError:
            pass

        try:
            _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
            for candidate in addresses:
                if candidate and not candidate.startswith("127."):
                    return candidate
        except OSError:
            pass

        return None
