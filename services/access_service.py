"""RFID card enrollment and access policy service."""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from config import config
from drivers.pn532 import PN532Reader
from data.event_store import EventStore

logger = logging.getLogger(__name__)


class AccessService:
    """Own RFID reader access and card authorization rules."""

    def __init__(
        self,
        reader_factory=PN532Reader,
        *,
        store_path: str | Path | None = None,
        event_store: EventStore | None = None,
        card_detect_callback=None,
    ) -> None:
        self._reader_factory = reader_factory
        self._event_store = event_store
        self._card_detect_callback = card_detect_callback
        self._store_path = Path(store_path) if store_path is not None else Path(config.storage.card_store_path)
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._started = False
        self._reader = None
        self._reader_enabled = False
        self._last_error: str | None = None
        self._cards: dict[str, dict] = {}
        self._last_detected_uid: str | None = None
        self._load_cards_locked()

    def start(self) -> None:
        """Initialize the RFID reader if available."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._last_error = None
            self._initialize_reader_locked()
            logger.info(
                "Access service started: reader_enabled=%s card_count=%s",
                self._reader_enabled,
                len(self._cards),
            )

    def stop(self) -> None:
        """Release RFID reader resources."""
        with self._lock:
            reader = self._reader
            self._reader = None
            self._reader_enabled = False
            self._started = False

        if reader is None:
            return

        cleanup = getattr(reader, "cleanup", None) or getattr(reader, "close", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass
        logger.info("Access service stopped")

    def restart_reader(self) -> dict:
        """Recreate the RFID reader instance after a recoverable hardware error."""
        with self._io_lock:
            with self._lock:
                reader = self._reader
                self._reader = None
                self._reader_enabled = False

            if reader is not None:
                cleanup = getattr(reader, "cleanup", None) or getattr(reader, "close", None)
                if callable(cleanup):
                    try:
                        cleanup()
                    except Exception:
                        pass

            with self._lock:
                self._last_error = None
                if self._started:
                    self._initialize_reader_locked()
                return {
                    "started": self._started,
                    "reader_enabled": self._reader_enabled,
                    "last_error": self._last_error,
                }

    def get_status(self) -> dict:
        """Return reader and card-store status."""
        with self._lock:
            store_backend = "sqlite" if self._event_store is not None else "json"
            database_path = None
            if self._event_store is not None:
                database_path = self._event_store.get_status().get("database_path")
            return {
                "started": self._started,
                "enabled": config.rfid.enabled,
                "reader_enabled": self._reader_enabled,
                "card_count": len(self._cards),
                "last_error": self._last_error,
                "store_backend": store_backend,
                "store_path": str(self._store_path) if self._event_store is None else None,
                "database_path": database_path,
            }

    def list_cards(self) -> list[dict]:
        """Return all known cards."""
        with self._lock:
            return [copy.deepcopy(self._cards[uid]) for uid in sorted(self._cards)]

    def get_card(self, uid: str) -> dict | None:
        """Return one card record."""
        normalized_uid = self._normalize_uid(uid)
        with self._lock:
            card = self._cards.get(normalized_uid)
            return copy.deepcopy(card) if card is not None else None

    def enroll_card(
        self,
        uid: str,
        *,
        name: str | None = None,
        enabled: bool = True,
        access_windows: list[dict] | None = None,
        overwrite: bool = False,
    ) -> dict:
        """Create or replace a card record."""
        normalized_uid = self._normalize_uid(uid)
        normalized_windows = self._normalize_access_windows(access_windows or [])
        now = time.time()

        with self._lock:
            existing = self._cards.get(normalized_uid)
            if existing is not None and not overwrite:
                raise ValueError(f"Card {normalized_uid} already exists")

            created_at = existing["created_at"] if existing is not None else now
            card = {
                "uid": normalized_uid,
                "name": self._normalize_optional_text(name),
                "enabled": bool(enabled),
                "access_windows": normalized_windows,
                "created_at": created_at,
                "updated_at": now,
            }
            self._cards[normalized_uid] = card
            self._persist_card_locked(card)
            logger.info("RFID card enrolled: uid=%s overwrite=%s", normalized_uid, overwrite)
            return copy.deepcopy(self._cards[normalized_uid])

    def update_card(
        self,
        uid: str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        access_windows: list[dict] | None = None,
    ) -> dict:
        """Patch an existing card record."""
        normalized_uid = self._normalize_uid(uid)

        with self._lock:
            if normalized_uid not in self._cards:
                raise KeyError(f"Card {normalized_uid} does not exist")

            card = dict(self._cards[normalized_uid])
            if name is not None:
                card["name"] = self._normalize_optional_text(name)
            if enabled is not None:
                card["enabled"] = bool(enabled)
            if access_windows is not None:
                card["access_windows"] = self._normalize_access_windows(access_windows)

            card["updated_at"] = time.time()
            self._cards[normalized_uid] = card
            self._persist_card_locked(card)
            logger.info("RFID card updated: uid=%s", normalized_uid)
            return copy.deepcopy(self._cards[normalized_uid])

    def ensure_card_authorized(
        self,
        uid: str,
        *,
        name: str | None = None,
    ) -> dict:
        """Create or enable a card record while preserving existing schedules."""
        normalized_uid = self._normalize_uid(uid)
        normalized_name = self._normalize_optional_text(name)
        now = time.time()

        with self._lock:
            existing = self._cards.get(normalized_uid)
            if existing is None:
                card = {
                    "uid": normalized_uid,
                    "name": normalized_name,
                    "enabled": True,
                    "access_windows": [],
                    "created_at": now,
                    "updated_at": now,
                }
            else:
                card = dict(existing)
                if normalized_name is not None and card.get("name") is None:
                    card["name"] = normalized_name
                card["enabled"] = True
                card["updated_at"] = now

            self._cards[normalized_uid] = card
            self._persist_card_locked(card)
            logger.info("RFID card ensured authorized: uid=%s", normalized_uid)
            return copy.deepcopy(self._cards[normalized_uid])

    def scan_uid(self, timeout: float | None = None) -> str | None:
        """Read one RFID UID in hex."""
        with self._lock:
            if not self._reader_enabled or self._reader is None:
                return None
            reader = self._reader
            poll_interval = config.rfid.poll_interval_seconds

        with self._io_lock:
            uid = reader.read_uid_hex(timeout=timeout, poll_interval=poll_interval)
        if uid is None:
            self._clear_detected_uid_latch()
            return None
        normalized_uid = self._normalize_uid(uid)
        self._notify_card_detected(normalized_uid)
        logger.info("RFID UID detected: uid=%s timeout=%s", normalized_uid, timeout)
        return normalized_uid

    def reset_card_detect_latch(self) -> None:
        """Allow the next detected card UID to trigger the card-detect callback again."""
        self._clear_detected_uid_latch()

    def scan_card(self, *, timeout: float | None = None) -> dict | None:
        """Wait for one card and return its normalized UID."""
        self._clear_detected_uid_latch()
        uid = self.scan_uid(timeout=timeout)
        if uid is None:
            return None
        return {"uid": uid}

    def authorize_uid(self, uid: str, *, when: datetime | None = None) -> dict:
        """Evaluate access policy for one UID."""
        normalized_uid = self._normalize_uid(uid)
        access_time = when or datetime.now()

        with self._lock:
            card = copy.deepcopy(self._cards.get(normalized_uid))

        if card is None:
            result = self._build_access_result(
                uid=normalized_uid,
                allowed=False,
                reason="unknown_card",
                card=None,
                checked_at=access_time,
            )
            logger.info("RFID authorization denied: uid=%s reason=unknown_card", normalized_uid)
            return result

        if not card.get("enabled", False):
            result = self._build_access_result(
                uid=normalized_uid,
                allowed=False,
                reason="card_disabled",
                card=card,
                checked_at=access_time,
            )
            logger.info("RFID authorization denied: uid=%s reason=card_disabled", normalized_uid)
            return result

        if not self._is_allowed_by_windows(access_time, card.get("access_windows") or []):
            result = self._build_access_result(
                uid=normalized_uid,
                allowed=False,
                reason="outside_schedule",
                card=card,
                checked_at=access_time,
            )
            logger.info("RFID authorization denied: uid=%s reason=outside_schedule", normalized_uid)
            return result

        result = self._build_access_result(
            uid=normalized_uid,
            allowed=True,
            reason="granted",
            card=card,
            checked_at=access_time,
        )
        logger.info("RFID authorization granted: uid=%s", normalized_uid)
        return result

    def scan_and_authorize(self, timeout: float | None = None) -> dict | None:
        """Read one card and evaluate its access."""
        uid = self.scan_uid(timeout=timeout)
        if uid is None:
            return None
        return self.authorize_uid(uid)

    def _notify_card_detected(self, uid: str) -> None:
        callback = None
        with self._lock:
            if uid == self._last_detected_uid:
                return
            self._last_detected_uid = uid
            callback = self._card_detect_callback

        if callable(callback):
            try:
                callback()
            except Exception as error:
                logger.warning("RFID card-detect callback failed for uid=%s: %s", uid, error)
            else:
                logger.info("RFID card-detect callback fired: uid=%s", uid)

    def _clear_detected_uid_latch(self) -> None:
        with self._lock:
            self._last_detected_uid = None

    def _initialize_reader_locked(self) -> None:
        self._reader = None
        self._reader_enabled = False

        if not config.rfid.enabled:
            self._last_error = "rfid disabled in config"
            return

        try:
            reader = self._reader_factory(
                reset_pin=config.rfid.pn532_reset_pin,
                req_pin=config.rfid.pn532_req_pin,
            )
            if reader is None:
                raise RuntimeError("rfid reader factory returned no reader instance")
            self._reader = reader
            self._reader_enabled = True
            self._last_error = None
            logger.info(
                "RFID reader initialized: backend=pn532 reset_pin=%s req_pin=%s",
                config.rfid.pn532_reset_pin,
                config.rfid.pn532_req_pin,
            )
        except Exception as error:
            self._reader = None
            self._reader_enabled = False
            self._last_error = str(error)
            logger.warning("RFID reader initialization failed: %s", error)

    def _load_cards_locked(self) -> None:
        self._cards = {}

        if self._event_store is not None:
            raw_cards = self._event_store.list_cards()
            for raw_card in raw_cards:
                if not isinstance(raw_card, dict):
                    continue
                try:
                    normalized_card = self._normalize_card_record(raw_card)
                except Exception:
                    continue
                self._cards[normalized_card["uid"]] = normalized_card
            logger.info("Loaded %s RFID cards from sqlite", len(self._cards))
            return

        if self._store_path is None or not self._store_path.exists():
            return

        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        except Exception:
            return

        cards = payload.get("cards", [])
        if not isinstance(cards, list):
            return

        for raw_card in cards:
            if not isinstance(raw_card, dict):
                continue
            try:
                normalized_card = self._normalize_card_record(raw_card)
            except Exception:
                continue

            self._cards[normalized_card["uid"]] = normalized_card
        logger.info("Loaded %s RFID cards from JSON fallback", len(self._cards))

    def _persist_card_locked(self, card: dict) -> None:
        if self._event_store is not None:
            stored_card = self._event_store.upsert_card(card)
            normalized_card = self._normalize_card_record(stored_card)
            self._cards[normalized_card["uid"]] = normalized_card
            return

        self._save_cards_locked()

    def _save_cards_locked(self) -> None:
        if self._store_path is None:
            return

        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cards": [self._cards[uid] for uid in sorted(self._cards)],
            "updated_at": time.time(),
        }
        self._store_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def _normalize_card_record(self, raw_card: dict) -> dict:
        uid = self._normalize_uid(raw_card["uid"])
        return {
            "uid": uid,
            "name": self._normalize_optional_text(raw_card.get("name")),
            "enabled": bool(raw_card.get("enabled", True)),
            "access_windows": self._normalize_access_windows(raw_card.get("access_windows") or []),
            "created_at": float(raw_card.get("created_at", time.time())),
            "updated_at": float(raw_card.get("updated_at", time.time())),
        }

    @staticmethod
    def _normalize_uid(uid: str) -> str:
        filtered = "".join(character for character in str(uid).upper() if character in "0123456789ABCDEF")
        if not filtered:
            raise ValueError("uid must contain at least one hex character")
        if len(filtered) == 10:
            uid_bytes = bytes.fromhex(filtered)
            bcc = uid_bytes[0] ^ uid_bytes[1] ^ uid_bytes[2] ^ uid_bytes[3]
            if uid_bytes[4] == bcc:
                return filtered[:8]
        return filtered

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _normalize_access_windows(access_windows: list[dict]) -> list[dict]:
        normalized = []

        for raw_window in access_windows:
            if not isinstance(raw_window, dict):
                raise ValueError("access windows must be dictionaries")

            days = raw_window.get("days")
            if days is None:
                normalized_days = [0, 1, 2, 3, 4, 5, 6]
            else:
                normalized_days = sorted({int(day) for day in days})
                if any(day < 0 or day > 6 for day in normalized_days):
                    raise ValueError("access window days must be between 0 and 6")

            start = str(raw_window.get("start", "00:00")).strip()
            end = str(raw_window.get("end", "23:59")).strip()
            AccessService._validate_clock_text(start)
            AccessService._validate_clock_text(end)

            normalized.append(
                {
                    "days": normalized_days,
                    "start": start,
                    "end": end,
                }
            )

        return normalized

    @staticmethod
    def _validate_clock_text(value: str) -> None:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("time values must use HH:MM format")

        hour = int(parts[0])
        minute = int(parts[1])
        if not 0 <= hour <= 23:
            raise ValueError("hour must be between 0 and 23")
        if not 0 <= minute <= 59:
            raise ValueError("minute must be between 0 and 59")

    @staticmethod
    def _clock_minutes(value: str) -> int:
        hour_text, minute_text = value.split(":")
        return int(hour_text) * 60 + int(minute_text)

    def _is_allowed_by_windows(self, when: datetime, windows: list[dict]) -> bool:
        if not windows:
            return True

        weekday = when.weekday()
        current_minutes = when.hour * 60 + when.minute

        for window in windows:
            if weekday not in window["days"]:
                continue

            start_minutes = self._clock_minutes(window["start"])
            end_minutes = self._clock_minutes(window["end"])

            if start_minutes <= end_minutes:
                if start_minutes <= current_minutes <= end_minutes:
                    return True
                continue

            if current_minutes >= start_minutes or current_minutes <= end_minutes:
                return True

        return False

    @staticmethod
    def _build_access_result(
        *,
        uid: str,
        allowed: bool,
        reason: str,
        card: dict | None,
        checked_at: datetime,
    ) -> dict:
        return {
            "uid": uid,
            "allowed": allowed,
            "reason": reason,
            "checked_at": checked_at.isoformat(),
            "card": card,
        }
