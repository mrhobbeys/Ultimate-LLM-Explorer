"""Async-friendly SQLite wrapper with no third-party dependency.

We deliberately avoid ``aiosqlite`` (or any async DB driver) to keep the core
install tiny on a 256 MB Pi. Instead we own a single background thread and a
single persistent connection, and route every query through it. Because the
executor has exactly one worker, all access is serialized — safe with
``check_same_thread=False`` and no lock juggling in the callers.
"""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    xp            INTEGER NOT NULL DEFAULT 0,
    messages      INTEGER NOT NULL DEFAULT 0,
    rep           INTEGER NOT NULL DEFAULT 0,
    last_xp_ts    REAL    NOT NULL DEFAULT 0,
    infractions   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS rep_log (
    guild_id   INTEGER NOT NULL,
    giver_id   INTEGER NOT NULL,
    target_id  INTEGER NOT NULL,
    ts         REAL    NOT NULL,
    PRIMARY KEY (guild_id, giver_id, target_id)
);

CREATE TABLE IF NOT EXISTS mod_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER,
    user_id    INTEGER,
    channel_id INTEGER,
    kind       TEXT,           -- spam | profanity | llm | manual
    action     TEXT,           -- delete | timeout | ban | warn | shadow | log
    reason     TEXT,
    severity   REAL,
    ts         REAL
);

CREATE TABLE IF NOT EXISTS message_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    channel_id  INTEGER,
    user_id     INTEGER,
    message_id  INTEGER,
    kind        TEXT,          -- create | edit | delete
    content     TEXT,
    ts          REAL
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id  INTEGER NOT NULL,
    key       TEXT    NOT NULL,
    value     TEXT    NOT NULL,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS warnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER,
    user_id       INTEGER,
    moderator_id  INTEGER,
    reason        TEXT,
    ts            REAL
);

CREATE TABLE IF NOT EXISTS user_badges (
    guild_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    badge     TEXT    NOT NULL,
    ts        REAL,
    PRIMARY KEY (guild_id, user_id, badge)
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    target_id   INTEGER,
    channel_id  INTEGER,
    src_message INTEGER,       -- message that triggered it (for delete)
    dm_message  INTEGER,       -- the approval DM's message id (button lookup key)
    action      TEXT,          -- delete | timeout | kick | ban
    reason      TEXT,
    severity    REAL,
    status      TEXT,          -- pending | approved | denied | expired
    created_ts  REAL
);

CREATE INDEX IF NOT EXISTS idx_pending_dm ON pending_actions(dm_message);
CREATE INDEX IF NOT EXISTS idx_users_xp ON users(guild_id, xp DESC);
CREATE INDEX IF NOT EXISTS idx_mod_ts ON mod_events(guild_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_warn ON warnings(guild_id, user_id, ts DESC);
"""


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db")
        self._conn: sqlite3.Connection | None = None

    async def connect(self) -> None:
        await self._run(self._connect_sync)

    def _connect_sync(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL keeps writes cheap and readers non-blocking — good on slow SD cards.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA)
        conn.commit()
        self._conn = conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._run(self._conn.close)
            self._conn = None
        self._executor.shutdown(wait=True)

    async def _run(self, fn, *args) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, *args)

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        def _do() -> None:
            assert self._conn is not None
            self._conn.execute(sql, tuple(params))
            self._conn.commit()

        await self._run(_do)

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        def _do() -> sqlite3.Row | None:
            assert self._conn is not None
            cur = self._conn.execute(sql, tuple(params))
            return cur.fetchone()

        return await self._run(_do)

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        def _do() -> list[sqlite3.Row]:
            assert self._conn is not None
            cur = self._conn.execute(sql, tuple(params))
            return cur.fetchall()

        return await self._run(_do)

    async def backup(self, dest: str) -> str:
        """Online-backup the live DB to ``dest`` (consistent, no downtime)."""

        def _do() -> str:
            assert self._conn is not None
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            target = sqlite3.connect(dest)
            try:
                self._conn.backup(target)
            finally:
                target.close()
            return dest

        return await self._run(_do)
