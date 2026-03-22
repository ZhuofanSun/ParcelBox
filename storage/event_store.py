"""SQLite-backed event and snapshot persistence."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import time
from pathlib import Path

from config import config


class EventStore:
    """Persist snapshots and structured events in SQLite."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or config.storage.database_url
        self._db_path = self._resolve_db_path(self._database_url)
        self._lock = threading.Lock()
        self._started = False
        self._last_error: str | None = None

    def start(self) -> None:
        """Initialize the SQLite schema."""
        with self._lock:
            if self._started:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(self._schema_sql())
            self._started = True
            self._last_error = None

    def stop(self) -> None:
        """Mark the store as stopped."""
        with self._lock:
            self._started = False

    def get_status(self) -> dict:
        """Return database location and record counts."""
        self._ensure_started()
        with self._lock:
            try:
                with self._connect() as connection:
                    snapshot_count = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
                    event_count = connection.execute("SELECT COUNT(*) FROM event_logs").fetchone()[0]
                    card_count = connection.execute("SELECT COUNT(*) FROM rfid_cards").fetchone()[0]
            except Exception as error:
                self._last_error = str(error)
                snapshot_count = 0
                event_count = 0
                card_count = 0

            return {
                "started": self._started,
                "database_url": self._database_url,
                "database_path": str(self._db_path),
                "snapshot_count": snapshot_count,
                "event_count": event_count,
                "card_count": card_count,
                "last_error": self._last_error,
            }

    def list_cards(self) -> list[dict]:
        """Return all RFID cards stored in sqlite."""
        self._ensure_started()
        with self._lock:
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        """
                        SELECT payload_json
                        FROM rfid_cards
                        ORDER BY uid ASC
                        """
                    ).fetchall()
            except Exception as error:
                self._last_error = str(error)
                return []

            self._last_error = None

        return [json.loads(row["payload_json"]) for row in rows]

    def get_card(self, uid: str) -> dict | None:
        """Return one RFID card record from sqlite."""
        self._ensure_started()
        with self._lock:
            try:
                with self._connect() as connection:
                    row = connection.execute(
                        """
                        SELECT payload_json
                        FROM rfid_cards
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
        return json.loads(row["payload_json"])

    def upsert_card(self, card: dict) -> dict:
        """Insert or update one RFID card record."""
        self._ensure_started()
        card_copy = copy.deepcopy(card)
        with self._lock:
            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO rfid_cards (
                            uid,
                            name,
                            user_name,
                            enabled,
                            access_windows_json,
                            payload_json,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(uid) DO UPDATE SET
                            name = excluded.name,
                            user_name = excluded.user_name,
                            enabled = excluded.enabled,
                            access_windows_json = excluded.access_windows_json,
                            payload_json = excluded.payload_json,
                            created_at = excluded.created_at,
                            updated_at = excluded.updated_at
                        """,
                        (
                            card_copy.get("uid"),
                            card_copy.get("name"),
                            card_copy.get("user_name"),
                            self._coerce_allowed(card_copy.get("enabled")),
                            json.dumps(card_copy.get("access_windows") or [], ensure_ascii=False, sort_keys=True),
                            json.dumps(card_copy, ensure_ascii=False, sort_keys=True),
                            float(card_copy.get("created_at", time.time())),
                            float(card_copy.get("updated_at", time.time())),
                        ),
                    )
                    connection.commit()
            except Exception as error:
                self._last_error = str(error)
                return card_copy

            self._last_error = None
            return card_copy

    def record_event(self, category: str, event: dict) -> dict:
        """Insert one structured event and its snapshot if present."""
        self._ensure_started()
        event_copy = copy.deepcopy(event)
        with self._lock:
            try:
                with self._connect() as connection:
                    stored_event = self._record_event_with_connection(
                        connection,
                        category=category,
                        event=event_copy,
                    )
            except Exception as error:
                self._last_error = str(error)
                return event_copy

            self._last_error = None
            return stored_event

    def update_event(self, event: dict) -> dict:
        """Update an existing event row when the payload is enriched later."""
        self._ensure_started()
        event_copy = copy.deepcopy(event)
        storage_id = event_copy.get("storage_id")
        if storage_id is None:
            return self.record_event(event_copy.get("storage_category", "system"), event_copy)

        with self._lock:
            try:
                with self._connect() as connection:
                    snapshot_id = self._snapshot_id_for_event_with_connection(connection, event_copy)
                    connection.execute(
                        """
                        UPDATE event_logs
                        SET category = ?,
                            event_type = ?,
                            source = ?,
                            uid = ?,
                            allowed = ?,
                            reason = ?,
                            event_timestamp = ?,
                            snapshot_id = ?,
                            payload_json = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            event_copy.get("storage_category", "system"),
                            event_copy.get("type", "unknown"),
                            event_copy.get("source"),
                            event_copy.get("uid"),
                            self._coerce_allowed(event_copy.get("allowed")),
                            event_copy.get("reason"),
                            float(event_copy.get("timestamp", time.time())),
                            snapshot_id,
                            json.dumps(event_copy, ensure_ascii=False, sort_keys=True),
                            time.time(),
                            int(storage_id),
                        ),
                    )
                    connection.commit()
                    stored_event = self._enrich_event(event_copy, storage_id, event_copy.get("storage_category", "system"))
            except Exception as error:
                self._last_error = str(error)
                return event_copy

            self._last_error = None
            return stored_event

    def list_events(
        self,
        limit: int = 50,
        *,
        category: str | None = None,
    ) -> list[dict]:
        """Return recent persisted events."""
        self._ensure_started()
        safe_limit = max(int(limit), 0)
        with self._lock:
            try:
                with self._connect() as connection:
                    if category is None:
                        rows = connection.execute(
                            """
                            SELECT id, category, snapshot_id, payload_json
                            FROM event_logs
                            ORDER BY id DESC
                            LIMIT ?
                            """,
                            (safe_limit,),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            """
                            SELECT id, category, snapshot_id, payload_json
                            FROM event_logs
                            WHERE category = ?
                            ORDER BY id DESC
                            LIMIT ?
                            """,
                            (category, safe_limit),
                        ).fetchall()
            except Exception as error:
                self._last_error = str(error)
                return []

            self._last_error = None

        events = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload = self._enrich_event(payload, row["id"], row["category"])
            if row["snapshot_id"] is not None and isinstance(payload.get("snapshot"), dict):
                payload["snapshot"]["storage_id"] = row["snapshot_id"]
            events.append(payload)
        return events

    def _record_event_with_connection(self, connection, *, category: str, event: dict) -> dict:
        snapshot_id = self._snapshot_id_for_event_with_connection(connection, event)
        cursor = connection.execute(
            """
            INSERT INTO event_logs (
                category,
                event_type,
                source,
                uid,
                allowed,
                reason,
                event_timestamp,
                snapshot_id,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                event.get("type", "unknown"),
                event.get("source"),
                event.get("uid"),
                self._coerce_allowed(event.get("allowed")),
                event.get("reason"),
                float(event.get("timestamp", time.time())),
                snapshot_id,
                json.dumps(event, ensure_ascii=False, sort_keys=True),
                time.time(),
                time.time(),
            ),
        )
        connection.commit()
        stored_event = self._enrich_event(event, cursor.lastrowid, category)
        if snapshot_id is not None and isinstance(stored_event.get("snapshot"), dict):
            stored_event["snapshot"]["storage_id"] = snapshot_id
        return stored_event

    def _snapshot_id_for_event_with_connection(self, connection, event: dict) -> int | None:
        snapshot = event.get("snapshot")
        if not isinstance(snapshot, dict):
            return None

        existing_id = snapshot.get("storage_id")
        if existing_id is not None:
            return int(existing_id)

        cursor = connection.execute(
            """
            INSERT INTO snapshots (
                path,
                filename,
                saved_at,
                trigger,
                source,
                uid,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.get("path"),
                snapshot.get("filename"),
                snapshot.get("saved_at"),
                snapshot.get("trigger"),
                snapshot.get("source"),
                snapshot.get("uid"),
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                time.time(),
                time.time(),
            ),
        )
        snapshot["storage_id"] = cursor.lastrowid
        return cursor.lastrowid

    @staticmethod
    def _resolve_db_path(database_url: str) -> Path:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("Only sqlite:/// URLs are supported")
        raw_path = database_url[len(prefix) :]
        if raw_path.startswith("/"):
            return Path(raw_path)
        return Path(raw_path)

    @staticmethod
    def _schema_sql() -> str:
        return """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            filename TEXT,
            saved_at TEXT,
            trigger TEXT,
            source TEXT,
            uid TEXT,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rfid_cards (
            uid TEXT PRIMARY KEY,
            name TEXT,
            user_name TEXT,
            enabled INTEGER NOT NULL,
            access_windows_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS event_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT,
            uid TEXT,
            allowed INTEGER,
            reason TEXT,
            event_timestamp REAL NOT NULL,
            snapshot_id INTEGER,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_event_logs_category_id
        ON event_logs(category, id DESC);

        CREATE INDEX IF NOT EXISTS idx_snapshots_saved_at
        ON snapshots(saved_at DESC);

        CREATE INDEX IF NOT EXISTS idx_rfid_cards_updated_at
        ON rfid_cards(updated_at DESC);
        """

    @staticmethod
    def _enrich_event(event: dict, storage_id: int, category: str) -> dict:
        enriched = copy.deepcopy(event)
        enriched["storage_id"] = int(storage_id)
        enriched["storage_category"] = category
        return enriched

    @staticmethod
    def _coerce_allowed(value):
        if value is None:
            return None
        return 1 if bool(value) else 0

    def _ensure_started(self) -> None:
        if self._started:
            return
        self.start()

    def _connect(self):
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection
