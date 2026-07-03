"""SQLite persistence. Every player gets their own instance of the compromised
server: their own filesystem tree, their own NPC memories, their own progress.
Nothing here is shared between players, so one person's ``del`` or ``mv`` never
touches another's world — but within a world, state is durable and real.

The store is deliberately synchronous. SQLite on a local file is fast enough
that wrapping it in a thread pool would add latency, not remove it. Callers in
async contexts should hold the engine's lock around multi-step mutations.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    player_key   TEXT PRIMARY KEY,
    guild_id     TEXT,
    user_id      TEXT,
    mode         TEXT NOT NULL DEFAULT 'adventure',
    dialect      TEXT NOT NULL DEFAULT 'cmd',
    cwd          TEXT NOT NULL DEFAULT 'C:\\Users\\jmartin',
    username     TEXT NOT NULL DEFAULT 'jmartin',
    privilege    TEXT NOT NULL DEFAULT 'user',
    location     TEXT NOT NULL DEFAULT 'login',
    flags        TEXT NOT NULL DEFAULT '{}',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fs_nodes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_key   TEXT NOT NULL,
    parent_id    INTEGER,
    name         TEXT NOT NULL,
    name_lower   TEXT NOT NULL,
    kind         TEXT NOT NULL,              -- 'dir' | 'file'
    content      TEXT NOT NULL DEFAULT '',
    owner        TEXT NOT NULL DEFAULT 'jmartin',
    protected    INTEGER NOT NULL DEFAULT 0, -- system-protected: write needs admin
    hidden       INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    modified_at  REAL NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES fs_nodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fs_lookup ON fs_nodes(player_key, parent_id, name_lower);

CREATE TABLE IF NOT EXISTS npc_memory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_key   TEXT NOT NULL,
    npc_id       TEXT NOT NULL,
    role         TEXT NOT NULL,             -- 'player' | 'npc'
    content      TEXT NOT NULL,
    created_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_npc_mem ON npc_memory(player_key, npc_id, id);

CREATE TABLE IF NOT EXISTS journal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_key   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    detail       TEXT NOT NULL,
    created_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_journal ON journal(player_key, id);

CREATE TABLE IF NOT EXISTS sessions (
    channel_id   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    player_key   TEXT NOT NULL,
    created_at   REAL NOT NULL,
    PRIMARY KEY (channel_id, user_id)
);
"""


@dataclass
class Player:
    player_key: str
    guild_id: str | None
    user_id: str
    mode: str
    dialect: str
    cwd: str
    username: str
    privilege: str
    location: str
    flags: dict[str, Any]
    created_at: float
    updated_at: float


@dataclass
class Node:
    id: int
    player_key: str
    parent_id: int | None
    name: str
    kind: str
    content: str
    owner: str
    protected: bool
    hidden: bool
    created_at: float
    modified_at: float


def _node_from_row(row: sqlite3.Row) -> Node:
    return Node(
        id=row["id"],
        player_key=row["player_key"],
        parent_id=row["parent_id"],
        name=row["name"],
        kind=row["kind"],
        content=row["content"],
        owner=row["owner"],
        protected=bool(row["protected"]),
        hidden=bool(row["hidden"]),
        created_at=row["created_at"],
        modified_at=row["modified_at"],
    )


class Store:
    """Thin gateway over the SQLite file. One connection, WAL mode."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- players -------------------------------------------------------
    def get_player(self, player_key: str) -> Player | None:
        row = self.conn.execute(
            "SELECT * FROM players WHERE player_key = ?", (player_key,)
        ).fetchone()
        if row is None:
            return None
        return Player(
            player_key=row["player_key"],
            guild_id=row["guild_id"],
            user_id=row["user_id"],
            mode=row["mode"],
            dialect=row["dialect"],
            cwd=row["cwd"],
            username=row["username"],
            privilege=row["privilege"],
            location=row["location"],
            flags=json.loads(row["flags"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_player(
        self, player_key: str, guild_id: str | None, user_id: str
    ) -> Player:
        now = time.time()
        self.conn.execute(
            """INSERT INTO players (player_key, guild_id, user_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (player_key, guild_id, user_id, now, now),
        )
        self.conn.commit()
        player = self.get_player(player_key)
        assert player is not None
        return player

    def update_player(self, player_key: str, **fields: Any) -> None:
        if not fields:
            return
        if "flags" in fields and isinstance(fields["flags"], dict):
            fields["flags"] = json.dumps(fields["flags"])
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE players SET {cols} WHERE player_key = ?",
            (*fields.values(), player_key),
        )
        self.conn.commit()

    def delete_world(self, player_key: str) -> None:
        for table in ("fs_nodes", "npc_memory", "journal", "players"):
            self.conn.execute(f"DELETE FROM {table} WHERE player_key = ?", (player_key,))
        self.conn.commit()

    # ---- filesystem nodes ---------------------------------------------
    def add_node(
        self,
        player_key: str,
        parent_id: int | None,
        name: str,
        kind: str,
        content: str = "",
        owner: str = "jmartin",
        protected: bool = False,
        hidden: bool = False,
    ) -> int:
        now = time.time()
        cur = self.conn.execute(
            """INSERT INTO fs_nodes
               (player_key, parent_id, name, name_lower, kind, content, owner,
                protected, hidden, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_key,
                parent_id,
                name,
                name.lower(),
                kind,
                content,
                owner,
                int(protected),
                int(hidden),
                now,
                now,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_root(self, player_key: str) -> Node | None:
        row = self.conn.execute(
            "SELECT * FROM fs_nodes WHERE player_key = ? AND parent_id IS NULL LIMIT 1",
            (player_key,),
        ).fetchone()
        return _node_from_row(row) if row else None

    def get_node(self, node_id: int) -> Node | None:
        row = self.conn.execute(
            "SELECT * FROM fs_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return _node_from_row(row) if row else None

    def get_child(self, player_key: str, parent_id: int, name: str) -> Node | None:
        row = self.conn.execute(
            """SELECT * FROM fs_nodes
               WHERE player_key = ? AND parent_id = ? AND name_lower = ?""",
            (player_key, parent_id, name.lower()),
        ).fetchone()
        return _node_from_row(row) if row else None

    def list_children(self, player_key: str, parent_id: int) -> list[Node]:
        rows = self.conn.execute(
            """SELECT * FROM fs_nodes
               WHERE player_key = ? AND parent_id = ?
               ORDER BY kind DESC, name_lower ASC""",
            (player_key, parent_id),
        ).fetchall()
        return [_node_from_row(r) for r in rows]

    def set_content(self, node_id: int, content: str) -> None:
        self.conn.execute(
            "UPDATE fs_nodes SET content = ?, modified_at = ? WHERE id = ?",
            (content, time.time(), node_id),
        )
        self.conn.commit()

    def rename_node(self, node_id: int, name: str) -> None:
        self.conn.execute(
            "UPDATE fs_nodes SET name = ?, name_lower = ?, modified_at = ? WHERE id = ?",
            (name, name.lower(), time.time(), node_id),
        )
        self.conn.commit()

    def reparent_node(self, node_id: int, parent_id: int) -> None:
        self.conn.execute(
            "UPDATE fs_nodes SET parent_id = ?, modified_at = ? WHERE id = ?",
            (parent_id, time.time(), node_id),
        )
        self.conn.commit()

    def delete_node(self, node_id: int) -> None:
        # ON DELETE CASCADE handles the subtree.
        self.conn.execute("DELETE FROM fs_nodes WHERE id = ?", (node_id,))
        self.conn.commit()

    # ---- npc memory ----------------------------------------------------
    def add_memory(self, player_key: str, npc_id: str, role: str, content: str) -> None:
        self.conn.execute(
            """INSERT INTO npc_memory (player_key, npc_id, role, content, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (player_key, npc_id, role, content, time.time()),
        )
        self.conn.commit()

    def recent_memory(
        self, player_key: str, npc_id: str, limit: int = 20
    ) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            """SELECT role, content FROM npc_memory
               WHERE player_key = ? AND npc_id = ?
               ORDER BY id DESC LIMIT ?""",
            (player_key, npc_id, limit),
        ).fetchall()
        return [(r["role"], r["content"]) for r in reversed(rows)]

    # ---- journal -------------------------------------------------------
    def add_journal(self, player_key: str, kind: str, detail: str) -> None:
        self.conn.execute(
            "INSERT INTO journal (player_key, kind, detail, created_at) VALUES (?, ?, ?, ?)",
            (player_key, kind, detail, time.time()),
        )
        self.conn.commit()

    def journal_entries(self, player_key: str, limit: int = 30) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT kind, detail FROM journal WHERE player_key = ? ORDER BY id DESC LIMIT ?",
            (player_key, limit),
        ).fetchall()
        return [(r["kind"], r["detail"]) for r in reversed(rows)]

    # ---- discord sessions ---------------------------------------------
    def set_session(self, channel_id: str, user_id: str, player_key: str) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO sessions (channel_id, user_id, player_key, created_at)
               VALUES (?, ?, ?, ?)""",
            (channel_id, user_id, player_key, time.time()),
        )
        self.conn.commit()

    def get_session(self, channel_id: str, user_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT player_key FROM sessions WHERE channel_id = ? AND user_id = ?",
            (channel_id, user_id),
        ).fetchone()
        return row["player_key"] if row else None

    def clear_session(self, channel_id: str, user_id: str) -> None:
        self.conn.execute(
            "DELETE FROM sessions WHERE channel_id = ? AND user_id = ?",
            (channel_id, user_id),
        )
        self.conn.commit()

    def active_session_keys(self) -> Iterable[tuple[str, str]]:
        rows = self.conn.execute("SELECT channel_id, user_id FROM sessions").fetchall()
        return [(r["channel_id"], r["user_id"]) for r in rows]
