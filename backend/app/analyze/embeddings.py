"""Local embeddings via sentence-transformers, persisted to SQLite."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from ..config import settings

if TYPE_CHECKING:  # heavy import, defer to runtime
    from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        settings.embedding_model, cache_folder=str(settings.model_cache_dir)
    )


def encode(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    model = get_model()
    vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
    return vecs.astype(np.float32, copy=False)


def compute_missing(db: sqlite3.Connection, batch_size: int = 64) -> int:
    """Compute embeddings for messages that don't have one yet. Returns count."""
    rows = db.execute(
        """
        SELECT m.id, m.content
        FROM messages m
        LEFT JOIN embeddings e ON e.message_id = m.id
        WHERE e.message_id IS NULL
        ORDER BY m.created_at
        """
    ).fetchall()
    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        ids = [r[0] for r in batch]
        texts = [r[1] for r in batch]
        vecs = encode(texts)
        for mid, vec in zip(ids, vecs, strict=True):
            db.execute(
                "INSERT OR REPLACE INTO embeddings(message_id, vector, dim) VALUES (?, ?, ?)",
                (mid, vec.tobytes(), int(vec.shape[0])),
            )
            total += 1
    return total


def load_all(db: sqlite3.Connection) -> tuple[list[str], np.ndarray]:
    rows = db.execute("SELECT message_id, vector, dim FROM embeddings").fetchall()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)
    dim = rows[0][2]
    ids = [r[0] for r in rows]
    arr = np.stack(
        [np.frombuffer(r[1], dtype=np.float32).reshape(dim) for r in rows], axis=0
    )
    return ids, arr
