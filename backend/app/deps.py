"""FastAPI dependencies. Opens a per-request SQLite connection."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Depends

from .db import connect


def get_db() -> Iterator[sqlite3.Connection]:
    db = connect()
    try:
        yield db
    finally:
        db.close()


DBDep = Depends(get_db)
