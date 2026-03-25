"""One-time migration for email schemes from enabled/is_active to a single enabled flag."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from config import config


def resolve_db_path(argument: str | None) -> Path:
    source = argument or config.storage.database_url
    if source.startswith("sqlite:///"):
        return Path(source.removeprefix("sqlite:///")).expanduser().resolve()
    return Path(source).expanduser().resolve()


def choose_enabled_scheme_id(connection: sqlite3.Connection, has_is_active: bool) -> int | None:
    if has_is_active:
        row = connection.execute(
            """
            SELECT id
            FROM email_subscription_scheme
            WHERE is_active = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            return int(row["id"])

    row = connection.execute(
        """
        SELECT id
        FROM email_subscription_scheme
        WHERE enabled = 1
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return int(row["id"])


def migrate(db_path: Path) -> None:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    backup_path = db_path.with_name(f"{db_path.name}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(db_path, backup_path)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'email_subscription_scheme'
            """
        ).fetchone()
        if table is None:
            print(f"No email_subscription_scheme table found. Backup created at {backup_path}")
            return

        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(email_subscription_scheme)").fetchall()
        }
        chosen_id = choose_enabled_scheme_id(connection, "is_active" in columns)

        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP INDEX IF EXISTS idx_email_subscription_scheme_single_active")
        connection.execute("DROP INDEX IF EXISTS idx_email_subscription_scheme_single_enabled")

        if "is_active" in columns:
            connection.execute("ALTER TABLE email_subscription_scheme RENAME TO email_subscription_scheme_old")
            connection.execute(
                """
                CREATE TABLE email_subscription_scheme (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
                    username TEXT NOT NULL DEFAULT '',
                    password TEXT NOT NULL DEFAULT '',
                    from_address TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO email_subscription_scheme (
                    id,
                    name,
                    enabled,
                    username,
                    password,
                    from_address,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    name,
                    CASE WHEN ? IS NOT NULL AND id = ? THEN 1 ELSE 0 END,
                    username,
                    password,
                    from_address,
                    created_at,
                    updated_at
                FROM email_subscription_scheme_old
                ORDER BY id ASC
                """,
                (chosen_id, chosen_id),
            )
            connection.execute("DROP TABLE email_subscription_scheme_old")
        else:
            if chosen_id is None:
                connection.execute("UPDATE email_subscription_scheme SET enabled = 0")
            else:
                connection.execute(
                    """
                    UPDATE email_subscription_scheme
                    SET enabled = CASE WHEN id = ? THEN 1 ELSE 0 END
                    """,
                    (chosen_id,),
                )

        connection.execute("DROP INDEX IF EXISTS idx_email_subscription_recipient_scheme_id")
        connection.execute("ALTER TABLE email_subscription_recipient RENAME TO email_subscription_recipient_old")
        connection.execute(
            """
            CREATE TABLE email_subscription_recipient (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scheme_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (scheme_id) REFERENCES email_subscription_scheme(id) ON DELETE CASCADE,
                UNIQUE (scheme_id, email)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO email_subscription_recipient (
                id,
                scheme_id,
                email,
                created_at,
                updated_at
            )
            SELECT
                id,
                scheme_id,
                email,
                created_at,
                updated_at
            FROM email_subscription_recipient_old
            ORDER BY id ASC
            """
        )
        connection.execute("DROP TABLE email_subscription_recipient_old")
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_email_subscription_recipient_scheme_id
            ON email_subscription_recipient(scheme_id)
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_email_subscription_scheme_single_enabled
            ON email_subscription_scheme(enabled)
            WHERE enabled = 1
            """
        )
        max_id = connection.execute(
            "SELECT COALESCE(MAX(id), 0) FROM email_subscription_scheme"
        ).fetchone()[0]
        updated = connection.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = 'email_subscription_scheme'",
            (max_id,),
        )
        if updated.rowcount == 0:
            connection.execute(
                "INSERT INTO sqlite_sequence(name, seq) VALUES ('email_subscription_scheme', ?)",
                (max_id,),
            )
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON")
    finally:
        connection.close()

    print(f"Migration complete. Backup created at {backup_path}")
    print(f"Enabled scheme id: {chosen_id if chosen_id is not None else 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collapse email_subscription_scheme enabled/is_active into a single enabled flag."
    )
    parser.add_argument("--db", help="Path to SQLite database or sqlite:/// URL")
    args = parser.parse_args()
    migrate(resolve_db_path(args.db))


if __name__ == "__main__":
    main()
