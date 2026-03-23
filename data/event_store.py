"""SQLite-backed persistence for cards, access attempts, door sessions, and snapshots."""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)


class EventStore:
    """Persist the simplified locker data model in SQLite."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or config.storage.database_url
        self._db_path = self._resolve_db_path(self._database_url)
        self._schema_path = Path(__file__).with_name("schema.sql")
        self._lock = threading.Lock()
        self._started = False
        self._last_error: str | None = None

    def start(self) -> None:
        """Initialize the SQLite schema if needed."""
        with self._lock:
            if self._started:
                return

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(self._load_schema_sql())
            self._started = True
            self._last_error = None
            logger.info("SQLite event store started at %s", self._db_path)

    def stop(self) -> None:
        """Mark the store as stopped."""
        with self._lock:
            self._started = False
        logger.info("SQLite event store stopped")

    def get_status(self) -> dict:
        """Return database location and current record counts."""
        self._ensure_started()
        with self._lock:
            try:
                with self._connect() as connection:
                    card_count = self._scalar(connection, "SELECT COUNT(*) FROM rfid_card")
                    access_attempt_count = self._scalar(connection, "SELECT COUNT(*) FROM access_attempt")
                    door_session_count = self._scalar(connection, "SELECT COUNT(*) FROM door_session")
                    closed_session_count = self._scalar(
                        connection,
                        "SELECT COUNT(*) FROM door_session WHERE closed_at IS NOT NULL",
                    )
                    button_request_count = self._scalar(connection, "SELECT COUNT(*) FROM button_request")
                    snapshot_count = self._scalar(connection, "SELECT COUNT(*) FROM snapshot")
                    standalone_snapshot_count = self._scalar(
                        connection,
                        """
                        SELECT COUNT(*)
                        FROM snapshot
                        WHERE access_attempt_id IS NULL
                          AND button_request_id IS NULL
                        """,
                    )
                    event_count = (
                        access_attempt_count
                        + door_session_count
                        + closed_session_count
                        + button_request_count
                        + standalone_snapshot_count
                    )
            except Exception as error:
                self._last_error = str(error)
                card_count = 0
                access_attempt_count = 0
                door_session_count = 0
                button_request_count = 0
                snapshot_count = 0
                event_count = 0

            return {
                "started": self._started,
                "database_url": self._database_url,
                "database_path": str(self._db_path),
                "card_count": card_count,
                "access_attempt_count": access_attempt_count,
                "door_session_count": door_session_count,
                "button_request_count": button_request_count,
                "snapshot_count": snapshot_count,
                "event_count": event_count,
                "last_error": self._last_error,
            }

    def list_cards(self) -> list[dict]:
        """Return all known RFID cards."""
        self._ensure_started()
        with self._lock:
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        """
                        SELECT uid, name, enabled, access_window, created_at, updated_at
                        FROM rfid_card
                        ORDER BY uid ASC
                        """
                    ).fetchall()
            except Exception as error:
                self._last_error = str(error)
                return []

            self._last_error = None

        return [self._row_to_card(row) for row in rows]

    def get_card(self, uid: str) -> dict | None:
        """Return one RFID card record."""
        self._ensure_started()
        with self._lock:
            try:
                with self._connect() as connection:
                    row = connection.execute(
                        """
                        SELECT uid, name, enabled, access_window, created_at, updated_at
                        FROM rfid_card
                        WHERE uid = ?
                        """,
                        (str(uid),),
                    ).fetchone()
            except Exception as error:
                self._last_error = str(error)
                return None

            self._last_error = None

        if row is None:
            return None
        return self._row_to_card(row)

    def upsert_card(self, card: dict) -> dict:
        """Insert or update one RFID card record."""
        self._ensure_started()
        card_copy = copy.deepcopy(card)
        created_at_text = self._timestamp_to_text(card_copy.get("created_at"))
        updated_at_text = self._timestamp_to_text(card_copy.get("updated_at"))
        access_windows = copy.deepcopy(card_copy.get("access_windows") or [])
        with self._lock:
            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO rfid_card (
                            uid,
                            name,
                            enabled,
                            access_window,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(uid) DO UPDATE SET
                            name = excluded.name,
                            enabled = excluded.enabled,
                            access_window = excluded.access_window,
                            created_at = excluded.created_at,
                            updated_at = excluded.updated_at
                        """,
                        (
                            str(card_copy.get("uid")),
                            card_copy.get("name"),
                            self._coerce_bool(card_copy.get("enabled", True)),
                            self._serialize_access_window(access_windows),
                            created_at_text,
                            updated_at_text,
                        ),
                    )
                    connection.commit()
            except Exception as error:
                self._last_error = str(error)
                return card_copy

            self._last_error = None

        return {
            "uid": str(card_copy.get("uid")),
            "name": card_copy.get("name"),
            "enabled": bool(card_copy.get("enabled", True)),
            "access_windows": access_windows,
            "created_at": self._timestamp_to_epoch(created_at_text),
            "updated_at": self._timestamp_to_epoch(updated_at_text),
        }

    def record_access_attempt(
        self,
        *,
        card_uid: str,
        source: str,
        allowed: bool,
        reason: str,
        checked_at=None,
        snapshot: dict | None = None,
    ) -> dict:
        """Persist one RFID access attempt, optionally attaching a snapshot."""
        self._ensure_started()
        checked_at_text = self._timestamp_to_text(checked_at)
        with self._lock:
            try:
                with self._connect() as connection:
                    attempt_id = self._insert_access_attempt_with_connection(
                        connection,
                        card_uid=card_uid,
                        source=source,
                        allowed=allowed,
                        reason=reason,
                        checked_at_text=checked_at_text,
                    )
                    stored_snapshot = self._insert_snapshot_for_parent_with_connection(
                        connection,
                        snapshot,
                        access_attempt_id=attempt_id,
                        default_trigger="rfid",
                        default_timestamp=checked_at_text,
                    )
                    connection.commit()
            except Exception as error:
                self._last_error = str(error)
                return {"id": None, "snapshot": None}

            self._last_error = None

        return {
            "id": attempt_id,
            "checked_at": checked_at_text,
            "snapshot": stored_snapshot,
        }

    def open_door_session(
        self,
        *,
        open_source: str,
        opened_at=None,
        access_attempt_id: int | None = None,
    ) -> dict:
        """Persist one door-open session."""
        self._ensure_started()
        opened_at_text = self._timestamp_to_text(opened_at)
        with self._lock:
            try:
                with self._connect() as connection:
                    self._close_stale_open_sessions_with_connection(connection, opened_at_text)
                    session_id = self._insert_door_session_with_connection(
                        connection,
                        access_attempt_id=access_attempt_id,
                        open_source=open_source,
                        opened_at_text=opened_at_text,
                    )
                    connection.commit()
            except Exception as error:
                self._last_error = str(error)
                return {"id": None, "opened_at": opened_at_text}

            self._last_error = None

        return {
            "id": session_id,
            "opened_at": opened_at_text,
        }

    def close_door_session(
        self,
        *,
        close_source: str,
        closed_at=None,
        auto_closed: bool = False,
        occupancy: dict | None = None,
        create_if_missing: bool = True,
    ) -> dict:
        """Close the latest open door session and optionally attach occupancy data."""
        self._ensure_started()
        closed_at_text = self._timestamp_to_text(closed_at)
        with self._lock:
            try:
                with self._connect() as connection:
                    session_id = self._close_latest_open_session_with_connection(
                        connection,
                        close_source=close_source,
                        closed_at_text=closed_at_text,
                        auto_closed=auto_closed,
                    )
                    if session_id is None and create_if_missing:
                        session_id = self._insert_door_session_with_connection(
                            connection,
                            access_attempt_id=None,
                            open_source="implicit_open",
                            opened_at_text=closed_at_text,
                            close_source=close_source,
                            closed_at_text=closed_at_text,
                            auto_closed=auto_closed,
                        )
                    if session_id is not None and isinstance(occupancy, dict):
                        self._update_door_session_occupancy_with_connection(
                            connection,
                            session_id,
                            occupancy,
                        )
                    connection.commit()
            except Exception as error:
                self._last_error = str(error)
                return {"id": None, "closed_at": closed_at_text}

            self._last_error = None

        return {
            "id": session_id,
            "closed_at": closed_at_text,
        }

    def record_button_request(
        self,
        *,
        pressed_at=None,
        notification=None,
        notification_error: str | None = None,
        snapshot: dict | None = None,
    ) -> dict:
        """Persist one hardware button request, optionally attaching a snapshot."""
        self._ensure_started()
        pressed_at_text = self._timestamp_to_text(pressed_at)
        with self._lock:
            try:
                with self._connect() as connection:
                    button_request_id = self._insert_button_request_with_connection(
                        connection,
                        pressed_at_text=pressed_at_text,
                        notification=notification,
                        notification_error=notification_error,
                    )
                    stored_snapshot = self._insert_snapshot_for_parent_with_connection(
                        connection,
                        snapshot,
                        button_request_id=button_request_id,
                        default_trigger="button",
                        default_timestamp=pressed_at_text,
                    )
                    connection.commit()
            except Exception as error:
                self._last_error = str(error)
                return {"id": None, "snapshot": None}

            self._last_error = None

        return {
            "id": button_request_id,
            "pressed_at": pressed_at_text,
            "snapshot": stored_snapshot,
        }

    def record_snapshot(
        self,
        snapshot: dict | None,
        *,
        access_attempt_id: int | None = None,
        button_request_id: int | None = None,
        default_trigger: str | None = None,
        default_timestamp=None,
    ) -> dict | None:
        """Persist one snapshot and optionally attach it to a parent business record."""
        self._ensure_started()
        with self._lock:
            try:
                with self._connect() as connection:
                    stored_snapshot = self._insert_snapshot_for_parent_with_connection(
                        connection,
                        snapshot,
                        access_attempt_id=access_attempt_id,
                        button_request_id=button_request_id,
                        default_trigger=default_trigger,
                        default_timestamp=self._timestamp_to_text(default_timestamp),
                    )
                    connection.commit()
            except Exception as error:
                self._last_error = str(error)
                return None

            self._last_error = None

        return stored_snapshot

    def get_table_snapshot(self) -> dict:
        """Return all persisted business tables for live UI inspection."""
        self._ensure_started()
        with self._lock:
            try:
                with self._connect() as connection:
                    card_rows = connection.execute(
                        """
                        SELECT uid, name, enabled, access_window, created_at, updated_at
                        FROM rfid_card
                        ORDER BY updated_at DESC, uid ASC
                        """
                    ).fetchall()
                    access_attempt_rows = connection.execute(
                        """
                        SELECT id, card_uid, source, allowed, reason, checked_at
                        FROM access_attempt
                        ORDER BY id DESC
                        """
                    ).fetchall()
                    door_session_rows = connection.execute(
                        """
                        SELECT
                            id,
                            access_attempt_id,
                            open_source,
                            opened_at,
                            close_source,
                            closed_at,
                            auto_closed,
                            occupancy_state,
                            occupancy_distance_cm,
                            occupancy_measured_at
                        FROM door_session
                        ORDER BY id DESC
                        """
                    ).fetchall()
                    button_request_rows = connection.execute(
                        """
                        SELECT
                            id,
                            pressed_at,
                            email_sent,
                            email_duplicated,
                            email_sent_at,
                            email_error
                        FROM button_request
                        ORDER BY id DESC
                        """
                    ).fetchall()
                    snapshot_rows = connection.execute(
                        """
                        SELECT
                            id,
                            path,
                            filename,
                            trigger,
                            captured_at,
                            access_attempt_id,
                            button_request_id
                        FROM snapshot
                        ORDER BY id DESC
                        """
                    ).fetchall()
            except Exception as error:
                self._last_error = str(error)
                return {
                    "rfid_card": [],
                    "access_attempt": [],
                    "door_session": [],
                    "button_request": [],
                    "snapshot": [],
                }

            self._last_error = None

        return {
            "rfid_card": [self._row_to_card(row) for row in card_rows],
            "access_attempt": [self._row_to_access_attempt(row) for row in access_attempt_rows],
            "door_session": [self._row_to_door_session(row) for row in door_session_rows],
            "button_request": [self._row_to_button_request(row) for row in button_request_rows],
            "snapshot": [self._row_to_snapshot_table_entry(row) for row in snapshot_rows],
        }

    def list_events(self, limit: int = 50, *, category: str | None = None) -> list[dict]:
        """Return recent synthesized events."""
        self._ensure_started()
        safe_limit = max(int(limit), 0)
        with self._lock:
            try:
                with self._connect() as connection:
                    if category == "locker":
                        events = self._list_locker_events_with_connection(connection)
                    elif category == "button":
                        events = self._list_button_events_with_connection(connection)
                    elif category in {"snapshot", "vision"}:
                        events = self._list_standalone_snapshot_events_with_connection(connection)
                    else:
                        events = (
                            self._list_locker_events_with_connection(connection)
                            + self._list_button_events_with_connection(connection)
                            + self._list_standalone_snapshot_events_with_connection(connection)
                        )
            except Exception as error:
                self._last_error = str(error)
                return []

            self._last_error = None

        events.sort(key=self._event_sort_key, reverse=True)
        return events[:safe_limit]

    def _insert_access_attempt_with_connection(
        self,
        connection,
        *,
        card_uid,
        source,
        allowed,
        reason,
        checked_at_text: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO access_attempt (
                card_uid,
                source,
                allowed,
                reason,
                checked_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(card_uid),
                str(source or "unknown"),
                self._coerce_bool(allowed),
                str(reason or "unknown"),
                checked_at_text,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_door_session_with_connection(
        self,
        connection,
        *,
        access_attempt_id: int | None,
        open_source: str,
        opened_at_text: str,
        close_source: str | None = None,
        closed_at_text: str | None = None,
        auto_closed: bool = False,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO door_session (
                access_attempt_id,
                open_source,
                opened_at,
                close_source,
                closed_at,
                auto_closed
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                access_attempt_id,
                str(open_source or "unknown"),
                opened_at_text,
                None if close_source is None else str(close_source),
                closed_at_text,
                self._coerce_bool(auto_closed),
            ),
        )
        return int(cursor.lastrowid)

    def _close_latest_open_session_with_connection(
        self,
        connection,
        *,
        close_source: str,
        closed_at_text: str,
        auto_closed: bool,
    ) -> int | None:
        row = connection.execute(
            """
            SELECT id
            FROM door_session
            WHERE closed_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None

        session_id = int(row["id"])
        connection.execute(
            """
            UPDATE door_session
            SET close_source = ?,
                closed_at = ?,
                auto_closed = ?
            WHERE id = ?
            """,
            (
                str(close_source or "unknown"),
                closed_at_text,
                self._coerce_bool(auto_closed),
                session_id,
            ),
        )
        return session_id

    def _close_stale_open_sessions_with_connection(self, connection, closed_at_text: str) -> None:
        connection.execute(
            """
            UPDATE door_session
            SET close_source = COALESCE(close_source, 'reopened'),
                closed_at = COALESCE(closed_at, ?),
                auto_closed = COALESCE(auto_closed, 0)
            WHERE closed_at IS NULL
            """,
            (closed_at_text,),
        )

    def _update_door_session_occupancy_with_connection(self, connection, session_id: int, occupancy: dict) -> None:
        connection.execute(
            """
            UPDATE door_session
            SET occupancy_state = ?,
                occupancy_distance_cm = ?,
                occupancy_measured_at = ?
            WHERE id = ?
            """,
            (
                occupancy.get("state"),
                occupancy.get("distance_cm"),
                self._timestamp_to_text(occupancy.get("measured_at")),
                int(session_id),
            ),
        )

    def _insert_button_request_with_connection(
        self,
        connection,
        *,
        pressed_at_text: str,
        notification,
        notification_error: str | None,
    ) -> int:
        email_sent = False
        email_duplicated = False
        email_sent_at_text = None
        email_error = notification_error

        if isinstance(notification, dict):
            status = notification.get("status")
            if status == "sent":
                email_sent = True
                email_sent_at_text = self._timestamp_to_text(notification.get("timestamp"))
            elif status == "duplicate_filtered":
                email_duplicated = True
            elif status == "error":
                email_error = notification.get("error") or email_error

        cursor = connection.execute(
            """
            INSERT INTO button_request (
                pressed_at,
                email_sent,
                email_duplicated,
                email_sent_at,
                email_error
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                pressed_at_text,
                self._coerce_bool(email_sent),
                self._coerce_bool(email_duplicated),
                email_sent_at_text,
                email_error,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_snapshot_for_parent_with_connection(
        self,
        connection,
        snapshot: dict | None,
        *,
        access_attempt_id: int | None = None,
        button_request_id: int | None = None,
        default_trigger: str | None = None,
        default_timestamp: str | None = None,
    ) -> dict | None:
        if not isinstance(snapshot, dict):
            return None

        existing_id = snapshot.get("storage_id")
        if existing_id is not None:
            row = self._snapshot_row_by_id_with_connection(connection, int(existing_id))
            return None if row is None else self._row_to_snapshot(row)

        if access_attempt_id is not None:
            existing_row = connection.execute(
                "SELECT id, path, filename, trigger, captured_at FROM snapshot WHERE access_attempt_id = ?",
                (int(access_attempt_id),),
            ).fetchone()
            if existing_row is not None:
                return self._row_to_snapshot(existing_row)

        if button_request_id is not None:
            existing_row = connection.execute(
                "SELECT id, path, filename, trigger, captured_at FROM snapshot WHERE button_request_id = ?",
                (int(button_request_id),),
            ).fetchone()
            if existing_row is not None:
                return self._row_to_snapshot(existing_row)

        path = snapshot.get("path")
        if not path:
            return None

        filename = snapshot.get("filename") or Path(str(path)).name
        trigger = snapshot.get("trigger") or default_trigger or "snapshot"
        captured_at_text = self._timestamp_to_text(
            snapshot.get("captured_at") or snapshot.get("saved_at") or default_timestamp
        )

        cursor = connection.execute(
            """
            INSERT INTO snapshot (
                path,
                filename,
                trigger,
                captured_at,
                access_attempt_id,
                button_request_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                str(filename),
                str(trigger),
                captured_at_text,
                access_attempt_id,
                button_request_id,
            ),
        )
        row = self._snapshot_row_by_id_with_connection(connection, int(cursor.lastrowid))
        return None if row is None else self._row_to_snapshot(row)

    def _snapshot_row_by_id_with_connection(self, connection, snapshot_id: int):
        return connection.execute(
            """
            SELECT id, path, filename, trigger, captured_at
            FROM snapshot
            WHERE id = ?
            """,
            (int(snapshot_id),),
        ).fetchone()

    def _list_locker_events_with_connection(self, connection) -> list[dict]:
        events: list[dict] = []

        denied_rows = connection.execute(
            """
            SELECT id, card_uid, source, reason, checked_at
            FROM access_attempt
            WHERE allowed = 0
            """
        ).fetchall()
        for row in denied_rows:
            event = {
                "type": "access_denied",
                "source": row["source"],
                "uid": row["card_uid"],
                "allowed": False,
                "reason": row["reason"],
                "timestamp": self._timestamp_to_epoch(row["checked_at"]),
                "storage_id": int(row["id"]),
                "storage_category": "locker",
            }
            snapshot = self._snapshot_for_access_attempt_with_connection(connection, int(row["id"]))
            if snapshot is not None:
                event["snapshot"] = snapshot
            events.append(event)

        session_rows = connection.execute(
            """
            SELECT
                ds.id,
                ds.access_attempt_id,
                ds.open_source,
                ds.opened_at,
                ds.close_source,
                ds.closed_at,
                ds.auto_closed,
                ds.occupancy_state,
                ds.occupancy_distance_cm,
                ds.occupancy_measured_at,
                aa.card_uid,
                aa.reason AS access_reason
            FROM door_session ds
            LEFT JOIN access_attempt aa ON aa.id = ds.access_attempt_id
            """
        ).fetchall()
        for row in session_rows:
            open_event = {
                "type": "door_opened",
                "source": row["open_source"],
                "uid": row["card_uid"],
                "allowed": True,
                "reason": row["access_reason"] or "manual_open",
                "timestamp": self._timestamp_to_epoch(row["opened_at"]),
                "storage_id": int(row["id"]),
                "storage_category": "locker",
            }
            snapshot = None
            if row["access_attempt_id"] is not None:
                snapshot = self._snapshot_for_access_attempt_with_connection(connection, int(row["access_attempt_id"]))
            if snapshot is not None:
                open_event["snapshot"] = snapshot
            events.append(open_event)

            if row["closed_at"] is not None:
                close_event = {
                    "type": "door_closed",
                    "source": row["close_source"],
                    "uid": None,
                    "allowed": True,
                    "reason": "manual_close" if row["close_source"] == "api" else row["close_source"],
                    "timestamp": self._timestamp_to_epoch(row["closed_at"]),
                    "storage_id": int(row["id"]),
                    "storage_category": "locker",
                }
                if row["occupancy_state"] is not None or row["occupancy_distance_cm"] is not None:
                    close_event["occupancy"] = {
                        "state": row["occupancy_state"],
                        "distance_cm": row["occupancy_distance_cm"],
                        "measured_at": self._timestamp_to_epoch(row["occupancy_measured_at"]),
                    }
                events.append(close_event)

        return events

    def _list_button_events_with_connection(self, connection) -> list[dict]:
        events: list[dict] = []
        rows = connection.execute(
            """
            SELECT id, pressed_at, email_sent, email_duplicated, email_sent_at, email_error
            FROM button_request
            """
        ).fetchall()
        for row in rows:
            event = {
                "id": int(row["id"]),
                "type": "button_pressed",
                "source": "hardware_button",
                "timestamp": self._timestamp_to_epoch(row["pressed_at"]),
                "storage_id": int(row["id"]),
                "storage_category": "button",
                "notification": self._notification_from_button_row(row),
            }
            if row["email_error"]:
                event["notification_error"] = row["email_error"]
            snapshot = self._snapshot_for_button_request_with_connection(connection, int(row["id"]))
            event["snapshot"] = snapshot
            events.append(event)
        return events

    def _list_standalone_snapshot_events_with_connection(self, connection) -> list[dict]:
        events: list[dict] = []
        rows = connection.execute(
            """
            SELECT id, path, filename, trigger, captured_at
            FROM snapshot
            WHERE access_attempt_id IS NULL
              AND button_request_id IS NULL
            """
        ).fetchall()
        for row in rows:
            snapshot = self._row_to_snapshot(row)
            trigger = snapshot.get("trigger")
            if trigger == "manual":
                event_type = "manual_snapshot_captured"
            elif trigger == "vision_face":
                event_type = "face_snapshot_captured"
            else:
                event_type = "snapshot_captured"
            events.append(
                {
                    "type": event_type,
                    "source": trigger,
                    "timestamp": self._timestamp_to_epoch(row["captured_at"]),
                    "storage_id": int(row["id"]),
                    "storage_category": "snapshot",
                    "snapshot": snapshot,
                }
            )
        return events

    def _snapshot_for_access_attempt_with_connection(self, connection, access_attempt_id: int) -> dict | None:
        row = connection.execute(
            """
            SELECT id, path, filename, trigger, captured_at
            FROM snapshot
            WHERE access_attempt_id = ?
            """,
            (int(access_attempt_id),),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def _snapshot_for_button_request_with_connection(self, connection, button_request_id: int) -> dict | None:
        row = connection.execute(
            """
            SELECT id, path, filename, trigger, captured_at
            FROM snapshot
            WHERE button_request_id = ?
            """,
            (int(button_request_id),),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    @staticmethod
    def _row_to_snapshot(row) -> dict:
        return {
            "storage_id": int(row["id"]),
            "path": row["path"],
            "filename": row["filename"],
            "trigger": row["trigger"],
            "saved_at": row["captured_at"],
            "captured_at": row["captured_at"],
        }

    @staticmethod
    def _row_to_access_attempt(row) -> dict:
        return {
            "id": int(row["id"]),
            "card_uid": row["card_uid"],
            "source": row["source"],
            "allowed": bool(row["allowed"]),
            "reason": row["reason"],
            "checked_at": row["checked_at"],
        }

    @staticmethod
    def _row_to_door_session(row) -> dict:
        return {
            "id": int(row["id"]),
            "access_attempt_id": row["access_attempt_id"],
            "open_source": row["open_source"],
            "opened_at": row["opened_at"],
            "close_source": row["close_source"],
            "closed_at": row["closed_at"],
            "auto_closed": bool(row["auto_closed"]),
            "occupancy_state": row["occupancy_state"],
            "occupancy_distance_cm": row["occupancy_distance_cm"],
            "occupancy_measured_at": row["occupancy_measured_at"],
        }

    @staticmethod
    def _row_to_button_request(row) -> dict:
        return {
            "id": int(row["id"]),
            "pressed_at": row["pressed_at"],
            "email_sent": bool(row["email_sent"]),
            "email_duplicated": bool(row["email_duplicated"]),
            "email_sent_at": row["email_sent_at"],
            "email_error": row["email_error"],
        }

    @staticmethod
    def _row_to_snapshot_table_entry(row) -> dict:
        return {
            "id": int(row["id"]),
            "path": row["path"],
            "filename": row["filename"],
            "trigger": row["trigger"],
            "captured_at": row["captured_at"],
            "access_attempt_id": row["access_attempt_id"],
            "button_request_id": row["button_request_id"],
        }

    def _row_to_card(self, row) -> dict:
        return {
            "uid": row["uid"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "access_windows": self._deserialize_access_window(row["access_window"]),
            "created_at": self._timestamp_to_epoch(row["created_at"]),
            "updated_at": self._timestamp_to_epoch(row["updated_at"]),
        }

    @staticmethod
    def _notification_from_button_row(row) -> dict | None:
        if row["email_duplicated"]:
            return {"status": "duplicate_filtered"}
        if row["email_sent"]:
            notification = {"status": "sent"}
            if row["email_sent_at"] is not None:
                notification["timestamp"] = EventStore._timestamp_to_epoch(row["email_sent_at"])
            return notification
        if row["email_error"]:
            return {"status": "error", "error": row["email_error"]}
        return None

    @staticmethod
    def _serialize_access_window(access_windows: list[dict]) -> str:
        return json.dumps(access_windows, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _deserialize_access_window(value: str | None) -> list[dict]:
        if not value:
            return []
        try:
            decoded = json.loads(value)
        except Exception:
            return []
        return decoded if isinstance(decoded, list) else []

    @staticmethod
    def _coerce_bool(value) -> int:
        return 1 if bool(value) else 0

    @staticmethod
    def _resolve_db_path(database_url: str) -> Path:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("Only sqlite:/// URLs are supported")
        raw_path = database_url[len(prefix) :]
        if raw_path.startswith("/"):
            return Path(raw_path)
        return Path(raw_path)

    def _load_schema_sql(self) -> str:
        return self._schema_path.read_text(encoding="utf-8")

    def _ensure_started(self) -> None:
        if self._started:
            return
        self.start()

    def _connect(self):
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _scalar(connection, sql: str, params: tuple = ()) -> int:
        return int(connection.execute(sql, params).fetchone()[0])

    @staticmethod
    def _timestamp_to_text(value) -> str:
        if value is None:
            return EventStore._timestamp_to_text(time.time())

        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")

        text = str(value).strip()
        if not text:
            return EventStore._timestamp_to_text(time.time())

        try:
            numeric = float(text)
        except Exception:
            return text
        return EventStore._timestamp_to_text(numeric)

    @staticmethod
    def _timestamp_to_epoch(value) -> float | None:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text:
            return None

        try:
            return float(text)
        except Exception:
            pass

        normalized = text
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except Exception:
            return None

    @staticmethod
    def _event_sort_key(event: dict) -> tuple[float, int]:
        timestamp = float(event.get("timestamp", 0.0))
        priority_map = {
            "door_closed": 3,
            "access_denied": 2,
            "door_opened": 1,
        }
        priority = priority_map.get(str(event.get("type", "")), 0)
        return (timestamp, priority)
