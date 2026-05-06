"""Persistence layer: write canonical records + sync FTS."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from .models import Conversation, Message


def save_conversation(db: sqlite3.Connection, conv: Conversation) -> None:
    db.execute(
        """
        INSERT INTO conversations (id, provider, external_id, title, created_at,
                                   updated_at, model, raw_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, external_id) DO UPDATE SET
            title=excluded.title,
            created_at=excluded.created_at,
            updated_at=excluded.updated_at,
            model=excluded.model,
            raw_ref=excluded.raw_ref
        """,
        (
            conv.id,
            conv.provider,
            conv.external_id,
            conv.title,
            conv.created_at,
            conv.updated_at,
            conv.model,
            conv.raw_ref,
        ),
    )


def save_messages(
    db: sqlite3.Connection, conversation_id: str, title: str | None, messages: Iterable[Message]
) -> int:
    count = 0
    for m in messages:
        db.execute(
            """
            INSERT OR REPLACE INTO messages
                (id, conversation_id, parent_id, role, content, created_at,
                 tokens, model, attachments_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m.id,
                conversation_id,
                m.parent_id,
                m.role,
                m.content,
                m.created_at,
                m.tokens,
                m.model,
                json.dumps(m.attachments) if m.attachments else None,
            ),
        )
        # Sync FTS via explicit rowid mapping.
        row = db.execute("SELECT rowid FROM messages WHERE id = ?", (m.id,)).fetchone()
        if row is not None:
            db.execute("DELETE FROM messages_fts WHERE rowid = ?", (row[0],))
            db.execute(
                "INSERT INTO messages_fts(rowid, content, title) VALUES (?, ?, ?)",
                (row[0], m.content, title or ""),
            )
        count += 1
    return count


def save_full(db: sqlite3.Connection, conv: Conversation) -> tuple[int, int]:
    save_conversation(db, conv)
    n = save_messages(db, conv.id, conv.title, conv.messages)
    return 1, n
