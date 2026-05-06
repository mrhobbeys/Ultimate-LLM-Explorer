"""Claude.ai export adapter.

The export is a JSON array of conversations. Each has:
    - uuid, name, created_at, updated_at
    - chat_messages: list of {uuid, text, sender, created_at, updated_at,
      content: [{type, text, ...}]}

``sender`` is ``human`` or ``assistant``. Text may be in ``text`` directly, or
in a ``content`` array of blocks; we concatenate all text-typed blocks.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import Conversation, Message
from .base import IngestContext


def _parse_ts(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _message_text(msg: dict[str, Any]) -> str:
    blocks = msg.get("content")
    if isinstance(blocks, list) and blocks:
        parts: list[str] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text"):
                parts.append(str(b["text"]))
        if parts:
            return "\n".join(parts).strip()
    text = msg.get("text")
    return (text or "").strip()


class ClaudeAdapter:
    name = "claude"

    def sniff(self, path: Path) -> bool:
        if path.suffix.lower() != ".json":
            return False
        try:
            with path.open("rb") as f:
                head = f.read(4096).decode("utf-8", errors="ignore")
        except OSError:
            return False
        return '"chat_messages"' in head and '"sender"' in head

    def parse(self, path: Path, ctx: IngestContext) -> Iterator[Conversation]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            ctx.error(f"{path}: invalid JSON ({e})")
            return

        convos = data if isinstance(data, list) else data.get("conversations") or []
        for convo in convos:
            try:
                yield self._parse_one(convo, ctx)
            except Exception as e:
                ctx.error(f"claude conversation {convo.get('uuid') or '?'}: {e}")

    def _parse_one(self, convo: dict[str, Any], ctx: IngestContext) -> Conversation:
        ext_id = convo.get("uuid") or convo.get("id") or ""
        title = convo.get("name") or convo.get("title")
        created = _parse_ts(convo.get("created_at"))
        updated = _parse_ts(convo.get("updated_at")) or created

        conv = Conversation(
            id=f"claude:{ext_id}",
            provider="claude",
            external_id=ext_id,
            title=title,
            created_at=created,
            updated_at=updated,
            raw_ref=str(ctx.source),
        )

        for i, msg in enumerate(convo.get("chat_messages") or []):
            sender = msg.get("sender") or "human"
            role = "user" if sender in {"human", "user"} else "assistant"
            text = _message_text(msg)
            if not text:
                continue
            mid = msg.get("uuid") or f"{ext_id}-{i}"
            conv.messages.append(
                Message(
                    id=f"claude:{ext_id}:{mid}",
                    conversation_id=conv.id,
                    role=role,  # type: ignore[arg-type]
                    content=text,
                    created_at=_parse_ts(msg.get("created_at")),
                )
            )
        return conv
