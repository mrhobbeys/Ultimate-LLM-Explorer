"""Search API."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from ..deps import get_db
from ..search import search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def do_search(
    q: str = Query(..., min_length=1),
    mode: str = Query("hybrid", pattern="^(hybrid|fts|semantic)$"),
    limit: int = Query(25, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    hits = search(db, q, mode=mode, limit=limit)
    return {"hits": [asdict(h) for h in hits]}
