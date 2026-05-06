"""Per-provider adapter tests against the JSON fixtures."""

from __future__ import annotations

from app.ingest import ADAPTERS
from app.ingest.base import IngestContext


def test_chatgpt_tree_flatten(fixtures_dir):
    path = fixtures_dir / "chatgpt_sample.json"
    adapter = ADAPTERS["chatgpt"]
    assert adapter.sniff(path)
    convos = list(adapter.parse(path, IngestContext(source=path)))
    assert len(convos) == 1
    c = convos[0]
    assert c.provider == "chatgpt"
    assert c.title == "Python decorators"
    # Primary branch yields 3 messages (user, assistant, user).
    roles = [m.role for m in c.messages]
    assert roles == ["user", "assistant", "user"]
    assert "decorators" in c.messages[0].content.lower()


def test_claude_text_variants(fixtures_dir):
    path = fixtures_dir / "claude_sample.json"
    adapter = ADAPTERS["claude"]
    assert adapter.sniff(path)
    convos = list(adapter.parse(path, IngestContext(source=path)))
    assert len(convos) == 1
    c = convos[0]
    assert c.provider == "claude"
    # Both the `content:[{type:text}]` and top-level `text:` variants parse.
    assert [m.role for m in c.messages] == ["user", "assistant"]
    assert "lifetimes" in c.messages[0].content.lower()
    assert "references" in c.messages[1].content.lower()


def test_gemini_filters_non_gemini(fixtures_dir):
    path = fixtures_dir / "gemini_sample.json"
    adapter = ADAPTERS["gemini"]
    assert adapter.sniff(path)
    convos = list(adapter.parse(path, IngestContext(source=path)))
    # YouTube entry should be skipped; two Gemini activities remain.
    assert len(convos) == 2
    assert all(c.provider == "gemini" for c in convos)
    first = convos[0]
    # The "Asked " prefix is stripped from the title.
    assert first.messages[0].content.startswith("What is quantum")
    # The first activity has a response; the second does not.
    assert any(m.role == "assistant" for m in first.messages)
