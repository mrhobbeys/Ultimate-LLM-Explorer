"""Progression API."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..analyze.progression import compute, earliest_latest_examples
from ..deps import get_db

router = APIRouter(prefix="/api/progression", tags=["progression"])


@router.get("")
def progression(
    topic_id: int | None = None, db: sqlite3.Connection = Depends(get_db)
) -> dict:
    data = compute(db, topic_id)
    examples = earliest_latest_examples(db, topic_id) if topic_id is not None else None
    return {"series": data, "examples": examples}
