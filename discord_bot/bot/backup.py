"""Standalone DB backup — run by the systemd timer or by hand.

    python -m bot.backup            # back up + prune to the last N
    KEEP_BACKUPS=30 python -m bot.backup

Uses SQLite's online backup API, so it's consistent even while the bot writes.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from .config import Config
from .db import Database


async def run() -> int:
    cfg = Config.load()
    keep = int(os.environ.get("KEEP_BACKUPS", "14"))
    backup_dir = Path(cfg.backup_dir or "data/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    db = Database(cfg.db_path)
    await db.connect()
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"bot-{ts}.db"
    try:
        await db.backup(str(dest))
    finally:
        await db.close()

    size = dest.stat().st_size / 1024
    print(f"backup: {dest} ({size:.0f} KiB)")

    # prune oldest beyond `keep`
    backups = sorted(backup_dir.glob("bot-*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
        print(f"pruned: {old}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
