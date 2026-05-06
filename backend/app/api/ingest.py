"""Ingest endpoints: upload files or point at a path."""

from __future__ import annotations

import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile

from ..analyze import embeddings, stats, topics
from ..config import settings
from ..deps import get_db
from ..ingest.service import ingest_path

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


def _post_ingest_tasks() -> None:
    from ..db import connect

    db = connect()
    try:
        embeddings.compute_missing(db)
        topics.rebuild(db)
        stats.rebuild_daily(db)
    finally:
        db.close()


@router.post("")
async def ingest_upload(
    background: BackgroundTasks,
    files: list[UploadFile],
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    if not files:
        raise HTTPException(400, "no files")
    saved: list[Path] = []
    for f in files:
        safe_name = Path(f.filename or f"upload-{uuid.uuid4().hex}").name
        dest = settings.uploads_dir / f"{int(time.time())}-{uuid.uuid4().hex[:6]}-{safe_name}"
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(dest)
    results = []
    for p in saved:
        results.extend([r.model_dump() for r in ingest_path(db, p)])
    background.add_task(_post_ingest_tasks)
    return {"results": results}


@router.post("/path")
def ingest_by_path(
    payload: dict, background: BackgroundTasks, db: sqlite3.Connection = Depends(get_db)
) -> dict:
    raw = payload.get("path")
    if not raw:
        raise HTTPException(400, "missing 'path'")
    p = Path(str(raw)).expanduser().resolve()
    if not p.exists():
        raise HTTPException(404, f"path not found: {p}")
    results = [r.model_dump() for r in ingest_path(db, p)]
    background.add_task(_post_ingest_tasks)
    return {"results": results}


@router.post("/rebuild")
def rebuild_indices(background: BackgroundTasks) -> dict:
    """Trigger a full re-run of embeddings / topics / stats."""
    background.add_task(_post_ingest_tasks)
    return {"status": "scheduled"}


@router.get("/status")
def status(db: sqlite3.Connection = Depends(get_db)) -> dict:
    convs = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    msgs = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    embs = db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    topics_n = db.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    return {
        "conversations": convs,
        "messages": msgs,
        "embeddings": embs,
        "topics": topics_n,
    }
