"""Optional LLM enrichment for NPC dialogue.

Three backends, auto-selected, all optional:
  * ``none``      – default. No LLM. NPCs use the rule-based engine (free).
  * ``ollama``    – a local model over http://localhost:11434 (free, no API cost).
  * ``anthropic`` – the Claude API (richest, but paid — opt in with a key).

The rest of the game never depends on this. If ``generate`` returns ``None``
(no backend, error, timeout, or refusal), the caller falls back to the
deterministic dialogue. Nothing here is required to run the bot.
"""

from __future__ import annotations

import json
import os
import urllib.request

from .config import config

Message = dict[str, str]  # {"role": "user"|"assistant", "content": ...}


def _select_backend() -> str:
    explicit = os.environ.get("ORACLE_LLM_BACKEND", "").strip().lower()
    if explicit in ("none", "off", "disabled"):
        return "none"
    if explicit in ("anthropic", "ollama"):
        return explicit
    if config.anthropic_api_key:
        return "anthropic"
    if os.environ.get("ORACLE_OLLAMA_URL") or explicit == "ollama":
        return "ollama"
    return "none"


class LLM:
    def __init__(self) -> None:
        self.backend = _select_backend()
        self._anthropic = None
        if self.backend == "anthropic":
            try:
                import anthropic  # noqa: F401

                self._anthropic = anthropic.AsyncAnthropic(
                    api_key=config.anthropic_api_key
                )
            except Exception:
                self.backend = "none"
        self.ollama_url = os.environ.get(
            "ORACLE_OLLAMA_URL", "http://localhost:11434"
        ).rstrip("/")
        self.ollama_model = os.environ.get("ORACLE_OLLAMA_MODEL", "llama3.1")

    @property
    def enabled(self) -> bool:
        return self.backend != "none"

    def describe(self) -> str:
        if self.backend == "anthropic":
            return f"LLM: Anthropic ({config.model})"
        if self.backend == "ollama":
            return f"LLM: Ollama ({self.ollama_model} @ {self.ollama_url})"
        return "LLM: off (free rule-based dialogue)"

    async def generate(
        self, system: str, history: list[Message], user_message: str
    ) -> str | None:
        if self.backend == "anthropic":
            return await self._gen_anthropic(system, history, user_message)
        if self.backend == "ollama":
            return await self._gen_ollama(system, history, user_message)
        return None

    async def _gen_anthropic(
        self, system: str, history: list[Message], user_message: str
    ) -> str | None:
        assert self._anthropic is not None
        messages = [*history, {"role": "user", "content": user_message}]
        try:
            resp = await self._anthropic.messages.create(
                model=config.model,
                max_tokens=config.llm_max_tokens,
                system=system,
                messages=messages,
            )
        except Exception:
            return None
        if getattr(resp, "stop_reason", None) == "refusal":
            return None
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        return text.strip() or None

    async def _gen_ollama(
        self, system: str, history: list[Message], user_message: str
    ) -> str | None:
        import asyncio

        payload = {
            "model": self.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                *history,
                {"role": "user", "content": user_message},
            ],
            "options": {"num_predict": config.llm_max_tokens},
        }

        def _call() -> str | None:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode("utf-8"))
                return (data.get("message", {}).get("content") or "").strip() or None
            except Exception:
                return None

        return await asyncio.to_thread(_call)
