"""Google Gemini adapter (via Google Takeout "My Activity → Gemini").

Takeout gives two formats:
    1. ``MyActivity.html`` — one document with many entries.
    2. ``MyActivity.json`` — a list of activity objects.

Each activity has a prompt the user typed and (sometimes) the model response,
time stamp, and product ("Gemini" / "Gemini Apps"). We group consecutive
activities with no session grouping — Takeout doesn't preserve conversation
threading — so each activity becomes a one-turn "conversation". This is lossy
but honest.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from ..models import Conversation, Message
from .base import IngestContext

_GEMINI_PRODUCTS = {"Gemini", "Gemini Apps", "Bard"}


def _parse_iso(s: str) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    # Fall back to Takeout's human-readable format (e.g. "Mar 14, 2024, 8:32:11 PM PDT").
    for fmt in ("%b %d, %Y, %I:%M:%S %p %Z", "%b %d, %Y, %I:%M:%S %p %Z"):
        try:
            return datetime.strptime(s.strip(), fmt).timestamp()
        except ValueError:
            continue
    return None


class GeminiAdapter:
    name = "gemini"

    def sniff(self, path: Path) -> bool:
        suf = path.suffix.lower()
        if suf == ".json":
            try:
                with path.open("rb") as f:
                    head = f.read(4096).decode("utf-8", errors="ignore")
            except OSError:
                return False
            return '"header"' in head and (
                '"Gemini"' in head or '"Gemini Apps"' in head or '"Bard"' in head
            )
        if suf in {".html", ".htm"}:
            try:
                with path.open("rb") as f:
                    head = f.read(8192).decode("utf-8", errors="ignore")
            except OSError:
                return False
            lower = head.lower()
            return "my activity" in lower and ("gemini" in lower or "bard" in lower)
        return False

    def parse(self, path: Path, ctx: IngestContext) -> Iterator[Conversation]:
        if path.suffix.lower() == ".json":
            yield from self._parse_json(path, ctx)
        else:
            yield from self._parse_html(path, ctx)

    def _parse_json(self, path: Path, ctx: IngestContext) -> Iterator[Conversation]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            ctx.error(f"{path}: invalid JSON ({e})")
            return
        if not isinstance(data, list):
            ctx.error(f"{path}: expected list at top level")
            return
        for i, item in enumerate(data):
            header = item.get("header")
            if header not in _GEMINI_PRODUCTS:
                continue
            title = (item.get("title") or "").strip()
            prompt = title.removeprefix("Asked ").removeprefix("Used ").strip()
            when = _parse_iso(item.get("time") or "")
            # Response may live in item["subtitles"] or be absent entirely.
            response = ""
            for blk in item.get("subtitles") or []:
                if isinstance(blk, dict) and blk.get("name"):
                    response = str(blk["name"])
                    break
            yield self._build(path, f"json-{i}", prompt, response, when, header)

    def _parse_html(self, path: Path, ctx: IngestContext) -> Iterator[Conversation]:
        try:
            soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
        except Exception as e:
            ctx.error(f"{path}: HTML parse error ({e})")
            return
        # Each activity is an outer cell. Takeout's class names change; the
        # stable signal is a repeated element containing a <br> then the date.
        cells = soup.select("div.outer-cell, div.mdl-cell")
        if not cells:
            cells = soup.find_all("div")
        for i, cell in enumerate(cells):
            text = cell.get_text("\n", strip=True)
            if not text or ("Gemini" not in text and "Bard" not in text):
                continue
            # First line is usually the product tag; skip it.
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if len(lines) < 2:
                continue
            # Heuristic: prompt is the second line; last line that parses as
            # a date becomes the timestamp.
            prompt = re.sub(r"^(Asked|Used)\s+", "", lines[1]).strip()
            when = None
            for ln in reversed(lines):
                when = _parse_iso(ln)
                if when:
                    break
            yield self._build(path, f"html-{i}", prompt, "", when, "Gemini")

    def _build(
        self,
        path: Path,
        idx: str,
        prompt: str,
        response: str,
        when: float | None,
        product: str,
    ) -> Conversation:
        ext_id = f"{path.name}:{idx}"
        conv_id = f"gemini:{ext_id}"
        title = (prompt[:80] + "…") if len(prompt) > 80 else prompt or "Gemini activity"
        msgs: list[Message] = []
        if prompt:
            msgs.append(
                Message(
                    id=f"{conv_id}:u",
                    conversation_id=conv_id,
                    role="user",
                    content=prompt,
                    created_at=when,
                )
            )
        if response:
            msgs.append(
                Message(
                    id=f"{conv_id}:a",
                    conversation_id=conv_id,
                    role="assistant",
                    content=response,
                    created_at=when,
                    model=product,
                )
            )
        return Conversation(
            id=conv_id,
            provider="gemini",
            external_id=ext_id,
            title=title,
            created_at=when,
            updated_at=when,
            model=product,
            raw_ref=str(path),
            messages=msgs,
        )
