"""ChatGPT ``conversations.json`` adapter.

The export is a list of conversation objects. Each conversation has a ``mapping``
dict: ``node_id -> {id, parent, children, message?}``. The primary thread is
reconstructed by walking from ``current_node`` back to the root through
``parent`` pointers.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..models import Conversation, Message
from .base import IngestContext


def _extract_text(content: dict[str, Any] | None) -> str:
    if not content:
        return ""
    parts = content.get("parts") or []
    out: list[str] = []
    for p in parts:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            text = p.get("text") or p.get("content") or ""
            if text:
                out.append(text)
    return "\n".join(out).strip()


def _walk_primary_branch(mapping: dict[str, Any], current_node: str | None) -> list[str]:
    """Walk parent pointers from ``current_node`` to root, then return the
    chronological node-id list (root first)."""
    if not current_node or current_node not in mapping:
        # Fallback: find any leaf and walk back.
        children_counts = {nid: len(n.get("children") or []) for nid, n in mapping.items()}
        leaves = [nid for nid, c in children_counts.items() if c == 0]
        if not leaves:
            return list(mapping.keys())
        current_node = leaves[0]

    chain: list[str] = []
    node_id: str | None = current_node
    seen: set[str] = set()
    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        chain.append(node_id)
        node_id = mapping[node_id].get("parent")
    chain.reverse()
    return chain


class ChatGPTAdapter:
    name = "chatgpt"

    def sniff(self, path: Path) -> bool:
        if path.suffix.lower() != ".json":
            return False
        try:
            with path.open("rb") as f:
                head = f.read(4096).decode("utf-8", errors="ignore")
        except OSError:
            return False
        # The export is a JSON array; markers unique to ChatGPT format.
        return '"mapping"' in head and (
            '"current_node"' in head or '"conversation_id"' in head
        )

    def parse(self, path: Path, ctx: IngestContext) -> Iterator[Conversation]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            ctx.error(f"{path}: invalid JSON ({e})")
            return
        if not isinstance(data, list):
            ctx.error(f"{path}: expected list at top level")
            return

        for convo in data:
            try:
                yield self._parse_one(convo, ctx)
            except Exception as e:  # keep ingest flowing per-conversation
                ctx.error(f"conversation {convo.get('id') or '?'}: {e}")

    def _parse_one(self, convo: dict[str, Any], ctx: IngestContext) -> Conversation:
        ext_id = convo.get("id") or convo.get("conversation_id") or ""
        title = convo.get("title") or None
        created = convo.get("create_time")
        updated = convo.get("update_time") or created
        mapping: dict[str, Any] = convo.get("mapping") or {}
        current = convo.get("current_node")
        order = _walk_primary_branch(mapping, current)

        conv = Conversation(
            id=f"chatgpt:{ext_id}",
            provider="chatgpt",
            external_id=ext_id,
            title=title,
            created_at=float(created) if created else None,
            updated_at=float(updated) if updated else None,
            raw_ref=str(ctx.source),
        )

        # Flatten primary branch; retain parent pointers for side branches if
        # future work wants them.
        models_seen: list[str] = []
        for node_id in order:
            node = mapping.get(node_id) or {}
            msg = node.get("message")
            if not msg:
                continue
            author = (msg.get("author") or {}).get("role") or "user"
            if author not in {"user", "assistant", "system", "tool"}:
                continue
            text = _extract_text(msg.get("content"))
            if not text:
                # Many system/tool nodes have empty content; drop them.
                continue
            created_at = msg.get("create_time")
            md = msg.get("metadata") or {}
            model = md.get("model_slug") or md.get("default_model_slug")
            if model and model not in models_seen:
                models_seen.append(model)
            conv.messages.append(
                Message(
                    id=f"chatgpt:{ext_id}:{msg.get('id') or node_id}",
                    conversation_id=conv.id,
                    parent_id=node.get("parent"),
                    role=author,  # type: ignore[arg-type]
                    content=text,
                    created_at=float(created_at) if created_at else None,
                    model=model,
                )
            )

        if models_seen and not conv.model:
            conv.model = models_seen[0]
        if conv.messages and conv.created_at is None:
            conv.created_at = conv.messages[0].created_at
        return conv
