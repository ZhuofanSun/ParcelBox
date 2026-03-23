PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rfid_card (
    uid TEXT PRIMARY KEY,
    name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    access_window TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS access_attempt (
    id INTEGER PRIMARY KEY,
    card_uid TEXT NOT NULL,
    source TEXT NOT NULL,
    allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
    reason TEXT NOT NULL,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS door_session (
    id INTEGER PRIMARY KEY,
    access_attempt_id INTEGER UNIQUE,
    open_source TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    close_source TEXT,
    closed_at TEXT,
    auto_closed INTEGER NOT NULL DEFAULT 0 CHECK (auto_closed IN (0, 1)),
    occupancy_state TEXT,
    occupancy_distance_cm REAL,
    occupancy_measured_at TEXT,
    FOREIGN KEY (access_attempt_id) REFERENCES access_attempt(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS button_request (
    id INTEGER PRIMARY KEY,
    pressed_at TEXT NOT NULL,
    email_sent INTEGER NOT NULL DEFAULT 0 CHECK (email_sent IN (0, 1)),
    email_duplicated INTEGER NOT NULL DEFAULT 0 CHECK (email_duplicated IN (0, 1)),
    email_sent_at TEXT,
    email_error TEXT,
    CHECK (NOT (email_sent = 1 AND email_duplicated = 1))
);

CREATE TABLE IF NOT EXISTS snapshot (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    trigger TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    access_attempt_id INTEGER UNIQUE,
    button_request_id INTEGER UNIQUE,
    FOREIGN KEY (access_attempt_id) REFERENCES access_attempt(id) ON DELETE SET NULL,
    FOREIGN KEY (button_request_id) REFERENCES button_request(id) ON DELETE SET NULL,
    CHECK (
        (CASE WHEN access_attempt_id IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN button_request_id IS NOT NULL THEN 1 ELSE 0 END) <= 1
    )
);

CREATE INDEX IF NOT EXISTS idx_rfid_card_updated_at
ON rfid_card(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_access_attempt_checked_at
ON access_attempt(checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_access_attempt_card_uid
ON access_attempt(card_uid);

CREATE INDEX IF NOT EXISTS idx_door_session_opened_at
ON door_session(opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_door_session_closed_at
ON door_session(closed_at DESC);

CREATE INDEX IF NOT EXISTS idx_button_request_pressed_at
ON button_request(pressed_at DESC);

CREATE INDEX IF NOT EXISTS idx_snapshot_captured_at
ON snapshot(captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_snapshot_trigger
ON snapshot(trigger);
