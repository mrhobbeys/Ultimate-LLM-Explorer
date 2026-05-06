"""Obsidian vault export endpoint."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..deps import get_db
from ..vault import export_vault

router = APIRouter(prefix="/api/export", tags=["export"])


@router.post("/vault")
def vault(payload: dict, db: sqlite3.Connection = Depends(get_db)) -> dict:
    raw = payload.get("path")
    dest = (
        Path(str(raw)).expanduser().resolve()
        if raw
        else settings.exports_dir / "obsidian-vault"
    )
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"cannot create destination: {e}") from e
    return export_vault(db, dest)
