"""Conversation browse + detail endpoints."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
def list_conversations(
    db: sqlite3.Connection = Depends(get_db),
    provider: str | None = None,
    q: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    where: list[str] = []
    params: list = []
    if provider:
        where.append("c.provider = ?")
        params.append(provider)
    if q:
        where.append("COALESCE(c.title, '') LIKE ?")
        params.append(f"%{q}%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"""
        SELECT c.id, c.provider, c.title, c.created_at, c.updated_at, c.model,
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS msg_count
        FROM conversations c
        {clause}
        ORDER BY COALESCE(c.updated_at, c.created_at) DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    total = db.execute(
        f"SELECT COUNT(*) FROM conversations c {clause}",
        params,
    ).fetchone()[0]
    return {
        "total": total,
        "items": [dict(r) for r in rows],
    }


@router.get("/{conv_id}")
def get_conversation(conv_id: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    c = db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    if c is None:
        raise HTTPException(404, "conversation not found")
    msgs = db.execute(
        """
        SELECT id, parent_id, role, content, created_at, tokens, model, attachments_json
        FROM messages WHERE conversation_id = ?
        ORDER BY COALESCE(created_at, 0), id
        """,
        (conv_id,),
    ).fetchall()
    topic_rows = db.execute(
        """
        SELECT t.id, t.label, ct.score
        FROM conversation_topics ct JOIN topics t ON t.id = ct.topic_id
        WHERE ct.conversation_id = ? ORDER BY ct.score DESC
        """,
        (conv_id,),
    ).fetchall()
    return {
        "conversation": dict(c),
        "messages": [
            {
                **{k: r[k] for k in r.keys() if k != "attachments_json"},
                "attachments": json.loads(r["attachments_json"] or "[]"),
            }
            for r in msgs
        ],
        "topics": [dict(r) for r in topic_rows],
    }
