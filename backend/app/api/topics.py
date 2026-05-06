"""Topic listing + detail endpoints."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from ..analyze.topics import list_topics
from ..deps import get_db

router = APIRouter(prefix="/api/topics", tags=["topics"])


@router.get("")
def topics_list(db: sqlite3.Connection = Depends(get_db)) -> dict:
    return {"items": list_topics(db)}


@router.get("/{topic_id}")
def topic_detail(topic_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict:
    t = db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if t is None:
        raise HTTPException(404, "topic not found")
    convs = db.execute(
        """
        SELECT c.id, c.title, c.provider, c.created_at, ct.score
        FROM conversation_topics ct
        JOIN conversations c ON c.id = ct.conversation_id
        WHERE ct.topic_id = ?
        ORDER BY ct.score DESC, c.created_at DESC
        LIMIT 50
        """,
        (topic_id,),
    ).fetchall()

    # Time-series: count of tagged user messages per month.
    series_rows = db.execute(
        """
        SELECT m.created_at
        FROM messages m
        JOIN conversation_topics ct ON ct.conversation_id = m.conversation_id
        WHERE ct.topic_id = ? AND m.role='user' AND m.created_at IS NOT NULL
        """,
        (topic_id,),
    ).fetchall()
    from collections import Counter

    buckets: Counter[str] = Counter()
    for r in series_rows:
        buckets[
            datetime.fromtimestamp(r["created_at"], tz=UTC).strftime("%Y-%m")
        ] += 1

    return {
        "topic": {
            "id": t["id"],
            "label": t["label"],
            "keywords": json.loads(t["keywords_json"] or "[]"),
        },
        "conversations": [dict(r) for r in convs],
        "series": [{"bucket": b, "count": c} for b, c in sorted(buckets.items())],
    }


@router.get("/graph/edges")
def topic_graph(db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Topic co-occurrence edges: two topics co-occur if they share a conversation."""
    rows = db.execute(
        """
        SELECT a.topic_id AS src, b.topic_id AS dst, COUNT(*) AS weight
        FROM conversation_topics a
        JOIN conversation_topics b
          ON a.conversation_id = b.conversation_id AND a.topic_id < b.topic_id
        GROUP BY a.topic_id, b.topic_id
        HAVING weight >= 2
        ORDER BY weight DESC
        """
    ).fetchall()
    return {"edges": [dict(r) for r in rows]}
