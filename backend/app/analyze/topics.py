"""Topic modeling over user messages using BERTopic."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import numpy as np


def _fetch_user_messages(
    db: sqlite3.Connection,
) -> tuple[list[str], list[str], np.ndarray, list[str]]:
    rows = db.execute(
        """
        SELECT m.id, m.content, m.conversation_id, e.vector, e.dim
        FROM messages m
        JOIN embeddings e ON e.message_id = m.id
        WHERE m.role = 'user'
        """
    ).fetchall()
    if not rows:
        return [], [], np.zeros((0, 0), dtype=np.float32), []
    dim = rows[0]["dim"]
    ids = [r["id"] for r in rows]
    conv_ids = [r["conversation_id"] for r in rows]
    texts = [r["content"] for r in rows]
    vecs = np.stack(
        [np.frombuffer(r["vector"], dtype=np.float32).reshape(dim) for r in rows]
    )
    return ids, conv_ids, vecs, texts


def rebuild(db: sqlite3.Connection, min_topic_size: int | None = None) -> int:
    """Run BERTopic on user-message embeddings. Returns topic count."""
    _ids, conv_ids, vecs, texts = _fetch_user_messages(db)
    if len(texts) < 10:
        return 0

    try:
        from bertopic import BERTopic
        from sklearn.feature_extraction.text import CountVectorizer
    except Exception:  # optional at import time
        return 0

    if min_topic_size is None:
        min_topic_size = max(5, len(texts) // 50)

    vectorizer = CountVectorizer(stop_words="english", min_df=2, ngram_range=(1, 2))
    model = BERTopic(
        embedding_model=None,
        min_topic_size=min_topic_size,
        vectorizer_model=vectorizer,
        calculate_probabilities=False,
        verbose=False,
    )
    topics, _ = model.fit_transform(texts, embeddings=vecs)

    info = model.get_topic_info()
    now = time.time()

    db.execute("DELETE FROM conversation_topics")
    db.execute("DELETE FROM topics")
    created = 0
    conv_topic_counts: dict[tuple[str, int], int] = {}
    for _, row in info.iterrows():
        tid = int(row["Topic"])
        if tid == -1:
            continue
        label = str(row.get("Name") or f"Topic {tid}")
        words = [w for w, _ in (model.get_topic(tid) or [])][:10]
        db.execute(
            "INSERT INTO topics(id, label, keywords_json, created_at) VALUES (?, ?, ?, ?)",
            (tid, label, json.dumps(words), now),
        )
        created += 1

    for cid, tid in zip(conv_ids, topics, strict=True):
        if tid == -1:
            continue
        key = (cid, int(tid))
        conv_topic_counts[key] = conv_topic_counts.get(key, 0) + 1
    for (cid, tid), score in conv_topic_counts.items():
        db.execute(
            """
            INSERT OR REPLACE INTO conversation_topics(conversation_id, topic_id, score)
            VALUES (?, ?, ?)
            """,
            (cid, tid, float(score)),
        )
    return created


def list_topics(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT t.id, t.label, t.keywords_json,
               COUNT(DISTINCT ct.conversation_id) AS conversation_count,
               COALESCE(SUM(ct.score), 0) AS message_count
        FROM topics t
        LEFT JOIN conversation_topics ct ON ct.topic_id = t.id
        GROUP BY t.id
        ORDER BY conversation_count DESC
        """
    ).fetchall()
    return [
        {
            "id": r["id"],
            "label": r["label"],
            "keywords": json.loads(r["keywords_json"] or "[]"),
            "conversation_count": r["conversation_count"],
            "message_count": int(r["message_count"] or 0),
        }
        for r in rows
    ]
