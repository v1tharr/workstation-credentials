import os
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id           INTEGER PRIMARY KEY,
    username     TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash      TEXT    NOT NULL,
    role         TEXT    NOT NULL CHECK (role IN ('owner', 'admin')),
    active       INTEGER NOT NULL DEFAULT 1,
    failed       INTEGER NOT NULL DEFAULT 0,
    locked_until REAL    NOT NULL DEFAULT 0,
    created_at   REAL    NOT NULL
);

-- columns: [{"key", "label", "secret"}], cards: раскладка страницы участника (JSON)
CREATE TABLE IF NOT EXISTS exams (
    id         INTEGER PRIMARY KEY,
    title      TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    columns    TEXT    NOT NULL,
    cards      TEXT    NOT NULL,
    created_at REAL    NOT NULL
);

-- рабочее место; data — зашифрованный JSON со значениями колонок мероприятия
CREATE TABLE IF NOT EXISTS slots (
    id      INTEGER PRIMARY KEY,
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    label   TEXT    NOT NULL,
    data    TEXT    NOT NULL,
    UNIQUE (exam_id, label)
);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY,
    code         TEXT    NOT NULL UNIQUE,
    status       TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'revoked')),
    slot_id      INTEGER REFERENCES slots(id) ON DELETE SET NULL,
    ip           TEXT,
    created_at   REAL    NOT NULL,
    activated_at REAL,
    activated_by TEXT
);
-- на одно рабочее место не больше одного активного участника
CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_slot
    ON sessions(slot_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS audit (
    id      INTEGER PRIMARY KEY,
    ts      REAL NOT NULL,
    admin   TEXT,
    action  TEXT NOT NULL,
    details TEXT
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    conn.close()
