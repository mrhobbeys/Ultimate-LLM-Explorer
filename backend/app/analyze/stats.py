"""Aggregate usage statistics."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime


def _bucket_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")


def rebuild_daily(db: sqlite3.Connection) -> int:
    rows = db.execute(
        """
        SELECT created_at, tokens, model
        FROM messages
        WHERE created_at IS NOT NULL
        """
    ).fetchall()
    by_day: dict[str, dict[str, object]] = {}
    for r in rows:
        day = _bucket_date(r["created_at"])
        bucket = by_day.setdefault(day, {"msgs": 0, "tokens": 0, "models": Counter()})
        bucket["msgs"] = int(bucket["msgs"]) + 1  # type: ignore[operator]
        bucket["tokens"] = int(bucket["tokens"]) + int(r["tokens"] or 0)  # type: ignore[operator]
        if r["model"]:
            bucket["models"][r["model"]] += 1  # type: ignore[index]

    db.execute("DELETE FROM daily_stats")
    for day, b in by_day.items():
        db.execute(
            """
            INSERT OR REPLACE INTO daily_stats(date, msg_count, token_count, models_json)
            VALUES (?, ?, ?, ?)
            """,
            (day, int(b["msgs"]), int(b["tokens"]), json.dumps(dict(b["models"]))),  # type: ignore[arg-type]
        )
    return len(by_day)


def summary(db: sqlite3.Connection) -> dict[str, object]:
    total_convs = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    total_msgs = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    total_tokens = db.execute("SELECT COALESCE(SUM(tokens),0) FROM messages").fetchone()[0]

    by_provider = {
        r["provider"]: r["c"]
        for r in db.execute(
            "SELECT provider, COUNT(*) c FROM conversations GROUP BY provider"
        )
    }

    models = {
        r["model"]: r["c"]
        for r in db.execute(
            """
            SELECT COALESCE(model, 'unknown') AS model, COUNT(*) c
            FROM messages WHERE role='assistant' GROUP BY COALESCE(model, 'unknown')
            """
        )
    }

    hour_rows = db.execute(
        """
        SELECT CAST(strftime('%H', datetime(created_at, 'unixepoch')) AS INTEGER) AS hour,
               COUNT(*) c
        FROM messages WHERE created_at IS NOT NULL
        GROUP BY hour ORDER BY hour
        """
    ).fetchall()
    hours = {int(r["hour"]): int(r["c"]) for r in hour_rows if r["hour"] is not None}

    length_rows = db.execute(
        """
        SELECT n FROM (
            SELECT COUNT(*) AS n FROM messages GROUP BY conversation_id
        )
        """
    ).fetchall()
    lengths = [r["n"] for r in length_rows]
    return {
        "conversations": total_convs,
        "messages": total_msgs,
        "tokens": total_tokens,
        "by_provider": by_provider,
        "assistant_models": models,
        "hours": hours,
        "conversation_lengths": lengths,
    }


def daily(db: sqlite3.Connection) -> list[dict[str, object]]:
    rows = db.execute(
        "SELECT date, msg_count, token_count, models_json FROM daily_stats ORDER BY date"
    ).fetchall()
    return [
        {
            "date": r["date"],
            "msg_count": r["msg_count"],
            "token_count": r["token_count"],
            "models": json.loads(r["models_json"] or "{}"),
        }
        for r in rows
    ]
