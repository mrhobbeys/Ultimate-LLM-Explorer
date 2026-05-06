"""Stats API."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..analyze.stats import daily, summary
from ..deps import get_db

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary")
def get_summary(db: sqlite3.Connection = Depends(get_db)) -> dict:
    return summary(db)


@router.get("/daily")
def get_daily(db: sqlite3.Connection = Depends(get_db)) -> dict:
    return {"days": daily(db)}
