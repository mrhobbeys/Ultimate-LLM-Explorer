"""Hybrid search: FTS5 (BM25) fused with semantic (faiss cosine) via RRF."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .analyze import embeddings as emb


@dataclass
class Hit:
    message_id: str
    conversation_id: str
    conversation_title: str | None
    role: str
    content: str
    created_at: float | None
    provider: str
    score: float


_FTS_UNSAFE = re.compile(r'["\\]')


def _fts_query(q: str) -> str:
    # Very light sanitation: strip quotes/backslashes, join terms with AND.
    cleaned = _FTS_UNSAFE.sub(" ", q).strip()
    terms = [t for t in cleaned.split() if t]
    return " AND ".join(f'"{t}"' for t in terms) if terms else ""


def _fts_search(db: sqlite3.Connection, q: str, limit: int) -> list[tuple[str, float]]:
    fq = _fts_query(q)
    if not fq:
        return []
    rows = db.execute(
        """
        SELECT m.id AS id, bm25(messages_fts) AS score
        FROM messages_fts
        JOIN messages m ON m.rowid = messages_fts.rowid
        WHERE messages_fts MATCH ?
        ORDER BY score LIMIT ?
        """,
        (fq, limit),
    ).fetchall()
    # bm25 returns lower-is-better; invert so higher is better.
    return [(r["id"], -float(r["score"])) for r in rows]


def _vector_search(db: sqlite3.Connection, q: str, limit: int) -> list[tuple[str, float]]:
    ids, mat = emb.load_all(db)
    if not ids:
        return []
    qv = emb.encode([q])
    if qv.shape[1] != mat.shape[1]:
        return []
    sims = (mat @ qv[0]).tolist()
    ranked = sorted(zip(ids, sims, strict=True), key=lambda x: x[1], reverse=True)[:limit]
    return [(mid, float(s)) for mid, s in ranked]


def _rrf(
    lists: list[list[tuple[str, float]]], k: int = 60
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked in lists:
        for rank, (mid, _) in enumerate(ranked):
            scores[mid] = scores.get(mid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def search(
    db: sqlite3.Connection, query: str, mode: str = "hybrid", limit: int = 25
) -> list[Hit]:
    if not query.strip():
        return []
    fts_hits = _fts_search(db, query, limit * 3) if mode in {"hybrid", "fts"} else []
    vec_hits = _vector_search(db, query, limit * 3) if mode in {"hybrid", "semantic"} else []

    if mode == "fts":
        ranked = fts_hits
    elif mode == "semantic":
        ranked = vec_hits
    else:
        ranked = _rrf([fts_hits, vec_hits])

    ids = [mid for mid, _ in ranked[:limit]]
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = {
        r["id"]: r
        for r in db.execute(
            f"""
            SELECT m.id, m.conversation_id, m.role, m.content, m.created_at,
                   c.title AS conversation_title, c.provider AS provider
            FROM messages m JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id IN ({placeholders})
            """,
            ids,
        ).fetchall()
    }
    out: list[Hit] = []
    for mid, score in ranked[:limit]:
        r = rows.get(mid)
        if r is None:
            continue
        content = r["content"] or ""
        snippet = content[:280] + ("…" if len(content) > 280 else "")
        out.append(
            Hit(
                message_id=r["id"],
                conversation_id=r["conversation_id"],
                conversation_title=r["conversation_title"],
                role=r["role"],
                content=snippet,
                created_at=r["created_at"],
                provider=r["provider"],
                score=score,
            )
        )
    return out
