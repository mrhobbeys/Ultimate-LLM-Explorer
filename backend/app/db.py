"""SQLite schema + connection helpers. FTS5 mirrors messages via triggers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    external_id   TEXT,
    title         TEXT,
    created_at    REAL,
    updated_at    REAL,
    model         TEXT,
    raw_ref       TEXT,
    UNIQUE(provider, external_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_provider ON conversations(provider);

CREATE TABLE IF NOT EXISTS messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    parent_id        TEXT,
    role             TEXT NOT NULL,
    content          TEXT NOT NULL,
    created_at       REAL,
    tokens           INTEGER,
    model            TEXT,
    attachments_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    title,
    content='',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS embeddings (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    vector     BLOB NOT NULL,
    dim        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    id           INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    keywords_json TEXT,
    created_at   REAL
);

CREATE TABLE IF NOT EXISTS conversation_topics (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    score           REAL,
    PRIMARY KEY (conversation_id, topic_id)
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date          TEXT PRIMARY KEY,
    msg_count     INTEGER NOT NULL,
    token_count   INTEGER NOT NULL,
    models_json   TEXT
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT,
    provider    TEXT,
    status      TEXT NOT NULL,
    message     TEXT,
    created_at  REAL,
    finished_at REAL,
    stats_json  TEXT
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or settings.db_path, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=NORMAL")
    return db


def init_db(path: Path | None = None) -> None:
    with connect(path) as db:
        db.executescript(SCHEMA)


@contextmanager
def transaction(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    db.execute("BEGIN")
    try:
        yield db
    except Exception:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def upsert_fts(db: sqlite3.Connection, rowid: str, content: str, title: str = "") -> None:
    """FTS5 is a virtual table; we manage it explicitly keyed by message.rowid.

    Note: messages.id is TEXT so we can't use its rowid directly. We store a
    hash of the id as FTS docid via a mapping table? Simpler: use messages.rowid
    from SQLite (auto). We look it up before inserting.
    """
    row = db.execute("SELECT rowid FROM messages WHERE id = ?", (rowid,)).fetchone()
    if row is None:
        return
    db.execute("DELETE FROM messages_fts WHERE rowid = ?", (row[0],))
    db.execute(
        "INSERT INTO messages_fts(rowid, content, title) VALUES (?, ?, ?)",
        (row[0], content, title),
    )
