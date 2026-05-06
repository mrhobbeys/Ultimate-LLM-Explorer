"""Obsidian-compatible vault exporter.

Layout::

    <vault>/
        Conversations/<provider>/<YYYY-MM-DD> - <slug>.md
        Daily/<YYYY-MM-DD>.md
        Topics/<topic-label>.md
        _Index.md

Each conversation note gets YAML frontmatter (title, date, provider, model,
tags) so Dataview and the built-in search can filter on them, plus wiki-links
to the matching Daily note, each attached Topic MOC, and top-k similar
conversations by embedding cosine.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..analyze import embeddings as emb

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(s: str, maxlen: int = 60) -> str:
    s = (s or "untitled").lower()
    s = _SLUG.sub("-", s).strip("-")
    return (s or "untitled")[:maxlen]


def _fmt_date(ts: float | None) -> str:
    if ts is None:
        return "unknown"
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")


def _fmt_datetime(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _frontmatter(data: dict) -> str:
    lines = ["---"]
    for k, v in data.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        elif v is None:
            continue
        else:
            safe = str(v).replace('"', "'")
            lines.append(f'{k}: "{safe}"')
    lines.append("---")
    return "\n".join(lines)


def _top_similar(
    conv_id: str,
    ids: list[str],
    mat: np.ndarray,
    id_to_conv: dict[str, str],
    k: int = 5,
) -> list[str]:
    """Return up to ``k`` other conversation IDs most similar to ``conv_id``."""
    if mat.size == 0:
        return []
    mask = np.array([id_to_conv.get(i) == conv_id for i in ids])
    if not mask.any():
        return []
    centroid = mat[mask].mean(axis=0)
    centroid /= max(np.linalg.norm(centroid), 1e-9)
    sims = mat @ centroid
    order = np.argsort(-sims)
    seen: set[str] = {conv_id}
    out: list[str] = []
    for idx in order:
        cid = id_to_conv.get(ids[idx])
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
        if len(out) >= k:
            break
    return out


def export_vault(db: sqlite3.Connection, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    conv_dir = dest / "Conversations"
    daily_dir = dest / "Daily"
    topic_dir = dest / "Topics"
    for d in (conv_dir, daily_dir, topic_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Preload embeddings for similarity links.
    emb_ids, emb_mat = emb.load_all(db)
    id_to_conv: dict[str, str] = {}
    if emb_ids:
        rows = db.execute(
            f"SELECT id, conversation_id FROM messages WHERE id IN ({','.join('?' * len(emb_ids))})",
            emb_ids,
        ).fetchall()
        id_to_conv = {r["id"]: r["conversation_id"] for r in rows}

    convs = db.execute("SELECT * FROM conversations ORDER BY created_at").fetchall()
    # Map conversation id -> output file stem for wiki-links.
    slug_map: dict[str, str] = {}
    days: dict[str, list[tuple[str, str]]] = defaultdict(list)  # date -> [(conv_id, slug)]
    topic_map: dict[int, dict] = {}
    topic_convs: dict[int, list[str]] = defaultdict(list)

    # Preload topics.
    for t in db.execute("SELECT * FROM topics").fetchall():
        topic_map[t["id"]] = {
            "label": t["label"],
            "keywords": json.loads(t["keywords_json"] or "[]"),
        }

    for c in convs:
        cid = c["id"]
        date = _fmt_date(c["created_at"])
        slug = f"{date} - {_slug(c['title'] or cid)}"
        slug_map[cid] = slug

        msgs = db.execute(
            """
            SELECT role, content, created_at, model
            FROM messages WHERE conversation_id = ?
            ORDER BY COALESCE(created_at, 0), id
            """,
            (cid,),
        ).fetchall()

        topic_rows = db.execute(
            """
            SELECT t.id, t.label FROM conversation_topics ct
            JOIN topics t ON t.id = ct.topic_id
            WHERE ct.conversation_id = ? ORDER BY ct.score DESC
            """,
            (cid,),
        ).fetchall()
        tags = [_slug(r["label"]) for r in topic_rows]
        for r in topic_rows:
            topic_convs[r["id"]].append(cid)

        similar_ids = _top_similar(cid, emb_ids, emb_mat, id_to_conv) if emb_ids else []

        fm = {
            "title": c["title"] or cid,
            "date": date,
            "provider": c["provider"],
            "model": c["model"],
            "conversation_id": cid,
            "tags": [f"llm/{c['provider']}", *tags],
        }
        body: list[str] = [_frontmatter(fm), "", f"# {c['title'] or cid}", ""]
        body.append(f"**Date:** {_fmt_datetime(c['created_at'])}  ")
        body.append(f"**Provider:** {c['provider']}  ")
        if c["model"]:
            body.append(f"**Model:** {c['model']}  ")
        body.append(f"**Daily:** [[Daily/{date}]]  ")
        if topic_rows:
            topic_links = " · ".join(f"[[Topics/{_slug(r['label'])}]]" for r in topic_rows)
            body.append(f"**Topics:** {topic_links}  ")
        body.append("")
        for m in msgs:
            role = (m["role"] or "user").capitalize()
            stamp = _fmt_datetime(m["created_at"])
            header = f"## {role}"
            if stamp:
                header += f" · {stamp}"
            body.append(header)
            body.append("")
            body.append(m["content"] or "")
            body.append("")
        if similar_ids:
            body.append("## Related")
            body.append("")
            for sid in similar_ids:
                sslug = slug_map.get(sid)
                if sslug:
                    body.append(f"- [[Conversations/{c['provider']}/{sslug}]]")
            body.append("")

        out = conv_dir / c["provider"] / f"{slug}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(body), encoding="utf-8")
        days[date].append((cid, slug))

    # Daily MOCs.
    for date, entries in days.items():
        fm = {"date": date, "tags": ["llm/daily"]}
        body = [_frontmatter(fm), "", f"# {date}", ""]
        for cid, slug in entries:
            prov = next((c["provider"] for c in convs if c["id"] == cid), "?")
            body.append(f"- [[Conversations/{prov}/{slug}]]")
        (daily_dir / f"{date}.md").write_text("\n".join(body), encoding="utf-8")

    # Topic MOCs.
    for tid, meta in topic_map.items():
        fm = {"label": meta["label"], "tags": ["llm/topic", *meta["keywords"][:5]]}
        body = [_frontmatter(fm), "", f"# {meta['label']}", ""]
        if meta["keywords"]:
            body.append("**Keywords:** " + ", ".join(meta["keywords"]))
            body.append("")
        for cid in topic_convs.get(tid, []):
            slug = slug_map.get(cid)
            prov = next((c["provider"] for c in convs if c["id"] == cid), "?")
            if slug:
                body.append(f"- [[Conversations/{prov}/{slug}]]")
        (topic_dir / f"{_slug(meta['label'])}.md").write_text(
            "\n".join(body), encoding="utf-8"
        )

    # Top-level index.
    index = [
        "# Ultimate LLM Explorer — Vault",
        "",
        f"- Conversations: {len(convs)}",
        f"- Topic MOCs: {len(topic_map)}",
        f"- Daily notes: {len(days)}",
        "",
        "## Entrypoints",
        "",
        "- [[Topics]]",
        "- [[Daily]]",
    ]
    (dest / "_Index.md").write_text("\n".join(index), encoding="utf-8")

    return {
        "vault": str(dest),
        "conversations": len(convs),
        "topics": len(topic_map),
        "days": len(days),
    }
