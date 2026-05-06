"""Ingest orchestration: detect → parse → store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..models import IngestResult
from ..storage import save_full
from ..tokens import count_tokens
from . import ADAPTERS, iter_sources
from .base import IngestContext


def ingest_path(db: sqlite3.Connection, path: Path) -> list[IngestResult]:
    results: list[IngestResult] = []
    for source in iter_sources(path):
        for name, adapter in ADAPTERS.items():
            try:
                if not adapter.sniff(source):
                    continue
            except Exception:
                continue
            ctx = IngestContext(source=source, raw_ref=str(source))
            convs = messages = 0
            for conv in adapter.parse(source, ctx):
                # Populate per-message token counts before saving.
                for m in conv.messages:
                    if m.tokens is None:
                        m.tokens = count_tokens(m.content)
                c, n = save_full(db, conv)
                convs += c
                messages += n
            results.append(
                IngestResult(
                    provider=name,  # type: ignore[arg-type]
                    source=str(source),
                    conversations=convs,
                    messages=messages,
                    errors=ctx.errors,
                )
            )
            break  # first-matching adapter wins
    return results
