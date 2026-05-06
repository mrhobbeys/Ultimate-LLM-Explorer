"""Per-topic skill progression: roll up user-message metrics over time."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")


def _month_bucket(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m")


def _ttr(words: list[str]) -> float:
    if not words:
        return 0.0
    return len(set(w.lower() for w in words)) / len(words)


def compute(db: sqlite3.Connection, topic_id: int | None) -> list[dict[str, object]]:
    if topic_id is None:
        rows = db.execute(
            """
            SELECT m.conversation_id, m.content, m.created_at
            FROM messages m
            WHERE m.role = 'user' AND m.created_at IS NOT NULL
            """
        ).fetchall()
        keywords: set[str] = set()
    else:
        kw_row = db.execute(
            "SELECT keywords_json FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        keywords = set(json.loads(kw_row["keywords_json"] or "[]")) if kw_row else set()
        rows = db.execute(
            """
            SELECT m.conversation_id, m.content, m.created_at
            FROM messages m
            JOIN conversation_topics ct
              ON ct.conversation_id = m.conversation_id AND ct.topic_id = ?
            WHERE m.role = 'user' AND m.created_at IS NOT NULL
            """,
            (topic_id,),
        ).fetchall()

    buckets: dict[str, dict[str, object]] = defaultdict(
        lambda: {"lens": [], "words": [], "conv_ids": set(), "topic_hits": 0, "total": 0}
    )
    for r in rows:
        bucket = _month_bucket(r["created_at"])
        words = _WORD.findall(r["content"] or "")
        b = buckets[bucket]
        b["lens"].append(len(r["content"] or ""))  # type: ignore[union-attr]
        b["words"].extend(w.lower() for w in words)  # type: ignore[union-attr]
        b["conv_ids"].add(r["conversation_id"])  # type: ignore[union-attr]
        b["total"] = int(b["total"]) + 1  # type: ignore[operator]
        if keywords:
            lowered = r["content"].lower() if r["content"] else ""
            hits = sum(1 for k in keywords if k in lowered)
            b["topic_hits"] = int(b["topic_hits"]) + hits  # type: ignore[operator]

    out: list[dict[str, object]] = []
    if not buckets:
        return out
    # Normalize components so they're comparable across buckets.
    avg_lens = [sum(b["lens"]) / len(b["lens"]) if b["lens"] else 0.0 for b in buckets.values()]  # type: ignore[arg-type,union-attr]
    ttrs = [_ttr(b["words"]) for b in buckets.values()]  # type: ignore[arg-type]
    followups = [
        (int(b["total"]) / len(b["conv_ids"])) if b["conv_ids"] else 0.0  # type: ignore[arg-type]
        for b in buckets.values()
    ]
    term_freqs = [
        (int(b["topic_hits"]) / max(1, int(b["total"]))) for b in buckets.values()
    ]
    mx_len = max(avg_lens, default=0.0) or 1.0
    mx_fu = max(followups, default=0.0) or 1.0
    mx_tf = max(term_freqs, default=0.0) or 1.0

    for (bucket, b), avg_len, ttr_v, fu, tf in zip(
        sorted(buckets.items()), avg_lens, ttrs, followups, term_freqs, strict=False
    ):
        norm = (
            (avg_len / mx_len) * 0.35
            + ttr_v * 0.25
            + (fu / mx_fu) * 0.20
            + (tf / mx_tf) * 0.20
        )
        out.append(
            {
                "bucket": bucket,
                "avg_user_len": round(avg_len, 2),
                "type_token_ratio": round(ttr_v, 4),
                "followups_per_conv": round(fu, 2),
                "topic_term_freq": round(tf, 4),
                "score": round(norm, 4) if not math.isnan(norm) else 0.0,
                "sample_count": int(b["total"]),
            }
        )
    return out


def earliest_latest_examples(
    db: sqlite3.Connection, topic_id: int
) -> dict[str, dict[str, object] | None]:
    def fetch(order: str) -> dict[str, object] | None:
        row = db.execute(
            f"""
            SELECT m.id, m.content, m.created_at, c.title
            FROM messages m
            JOIN conversation_topics ct
              ON ct.conversation_id = m.conversation_id AND ct.topic_id = ?
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.role = 'user' AND m.created_at IS NOT NULL
            ORDER BY m.created_at {order} LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "content": row["content"],
            "created_at": row["created_at"],
            "title": row["title"],
        }

    return {"earliest": fetch("ASC"), "latest": fetch("DESC")}
