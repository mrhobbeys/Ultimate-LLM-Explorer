"""Time-travel: calendar heatmap + per-day brief."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from ..deps import get_db

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


@router.get("/calendar")
def calendar(
    db: sqlite3.Connection = Depends(get_db),
    start: str | None = None,
    end: str | None = None,
) -> dict:
    where = []
    params: list = []
    if start:
        where.append("date >= ?")
        params.append(start)
    if end:
        where.append("date <= ?")
        params.append(end)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"SELECT date, msg_count, token_count, models_json FROM daily_stats {clause} ORDER BY date",
        params,
    ).fetchall()
    return {
        "days": [
            {
                "date": r["date"],
                "msg_count": r["msg_count"],
                "token_count": r["token_count"],
                "models": json.loads(r["models_json"] or "{}"),
            }
            for r in rows
        ]
    }


@router.get("/day/{date}")
def day(date: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    try:
        day_dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return {"error": "date must be YYYY-MM-DD"}
    start_ts = day_dt.timestamp()
    end_ts = start_ts + 86400

    convs = db.execute(
        """
        SELECT DISTINCT c.id, c.title, c.provider, c.model,
               MIN(m.created_at) AS first_at, COUNT(m.id) AS msg_count
        FROM conversations c JOIN messages m ON m.conversation_id = c.id
        WHERE m.created_at >= ? AND m.created_at < ?
        GROUP BY c.id
        ORDER BY first_at
        """,
        (start_ts, end_ts),
    ).fetchall()

    # Sample three user questions from the day as a brief.
    samples = db.execute(
        """
        SELECT content FROM messages
        WHERE role='user' AND created_at >= ? AND created_at < ?
        ORDER BY LENGTH(content) DESC LIMIT 3
        """,
        (start_ts, end_ts),
    ).fetchall()

    # Top topics for the day.
    topic_rows = db.execute(
        """
        SELECT t.id, t.label, COUNT(*) AS hits
        FROM messages m
        JOIN conversation_topics ct ON ct.conversation_id = m.conversation_id
        JOIN topics t ON t.id = ct.topic_id
        WHERE m.role='user' AND m.created_at >= ? AND m.created_at < ?
        GROUP BY t.id ORDER BY hits DESC LIMIT 5
        """,
        (start_ts, end_ts),
    ).fetchall()

    models = Counter()
    for c in convs:
        if c["model"]:
            models[c["model"]] += 1

    return {
        "date": date,
        "conversations": [dict(r) for r in convs],
        "top_topics": [dict(r) for r in topic_rows],
        "sample_questions": [r["content"] for r in samples],
        "models": dict(models),
    }
