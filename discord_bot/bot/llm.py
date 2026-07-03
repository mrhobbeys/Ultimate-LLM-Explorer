"""Offboard LLM routing.

The Pi does **no** inference. It routes ambiguous messages over HTTP to an
OpenAI-compatible endpoint (Ollama, llama.cpp server, LM Studio, vLLM, …)
running on some beefier box on the LAN, gets back a structured moderation
verdict, and acts on it deterministically. The model's text never reaches
chat — it only informs delete/timeout/ban decisions.

Guards for weak hardware:
  * A bounded queue + a tiny worker pool (1 on a Pi 1) so we never run two
    inferences at once and never buffer unbounded work.
  * A small LRU verdict cache keyed on normalized text.
  * A circuit breaker: after repeated failures we stop calling for a cooldown
    so a dead endpoint doesn't wedge the moderation pipeline.
  * aiohttp is reused from discord.py — no extra dependency.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass

import aiohttp

from .analysis import normalize_leet
from .config import LLMConfig

SYSTEM_PROMPT = (
    "You are a strict content-moderation classifier for a Discord server. "
    "You receive a single user message. Respond with ONLY a compact JSON object, "
    "no prose, no code fence, with exactly these keys:\n"
    '  "category": one of ["ok","spam","harassment","hate","sexual","threat",'
    '"self_harm","other"]\n'
    '  "severity": a float 0.0-1.0 (0 = harmless, 1 = egregious)\n'
    '  "reason": a short phrase (max 12 words)\n'
    "Judge only the text provided. If it is benign, return category ok and a low "
    "severity. Do not explain. Output JSON only."
)


@dataclass
class Verdict:
    category: str = "ok"
    severity: float = 0.0
    reason: str = ""
    ok: bool = True          # False if the call failed / endpoint unreachable

    @property
    def is_harmful(self) -> bool:
        return self.category != "ok" and self.severity > 0.0


class _LRU:
    def __init__(self, size: int) -> None:
        self._size = max(1, size)
        self._d: "OrderedDict[str, Verdict]" = OrderedDict()

    def get(self, key: str) -> Verdict | None:
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return None

    def put(self, key: str, value: Verdict) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self._size:
            self._d.popitem(last=False)


class LLMClient:
    def __init__(self, cfg: LLMConfig, cache_size: int = 512) -> None:
        self.cfg = cfg
        self._session: aiohttp.ClientSession | None = None
        self._sem = asyncio.Semaphore(max(1, cfg.max_workers))
        self._cache = _LRU(cache_size)
        # circuit breaker state
        self._fail_count = 0
        self._open_until = 0.0
        # metrics for the health cog
        self.calls = 0
        self.cache_hits = 0
        self.failures = 0
        self.total_latency = 0.0

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.cfg.timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def breaker_open(self) -> bool:
        return time.monotonic() < self._open_until

    def _trip_breaker(self) -> None:
        self._fail_count += 1
        if self._fail_count >= 3:
            # exponential-ish backoff capped at 5 min
            cooldown = min(300.0, 10.0 * self._fail_count)
            self._open_until = time.monotonic() + cooldown

    def _reset_breaker(self) -> None:
        self._fail_count = 0
        self._open_until = 0.0

    async def classify(self, text: str) -> Verdict:
        if not self.cfg.enabled or self._session is None:
            return Verdict(ok=False)
        key = normalize_leet(text)[:256]
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        if self.breaker_open:
            return Verdict(ok=False, reason="breaker_open")

        async with self._sem:  # throttle concurrent inferences
            verdict = await self._request(text)

        if verdict.ok:
            self._reset_breaker()
            self._cache.put(key, verdict)
        else:
            self._trip_breaker()
        return verdict

    async def _request(self, text: str) -> Verdict:
        assert self._session is not None
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text[:2000]},
            ],
            "temperature": 0.0,
            "max_tokens": self.cfg.max_tokens,
            "stream": False,
        }
        start = time.monotonic()
        self.calls += 1
        try:
            async with self._session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    self.failures += 1
                    return Verdict(ok=False, reason=f"http_{resp.status}")
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001 - want any network error handled
            self.failures += 1
            return Verdict(ok=False, reason=f"error:{type(exc).__name__}")
        finally:
            self.total_latency += time.monotonic() - start

        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        return self._parse(content)

    @staticmethod
    def _parse(content: str) -> Verdict:
        raw = content.strip()
        # tolerate models that wrap JSON in a code fence or add stray text
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return Verdict(ok=False, reason="no_json")
        try:
            obj = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return Verdict(ok=False, reason="bad_json")
        try:
            severity = float(obj.get("severity", 0.0))
        except (TypeError, ValueError):
            severity = 0.0
        category = str(obj.get("category", "ok")).lower().strip()
        return Verdict(
            category=category or "ok",
            severity=max(0.0, min(1.0, severity)),
            reason=str(obj.get("reason", ""))[:120],
            ok=True,
        )

    @property
    def avg_latency(self) -> float:
        return (self.total_latency / self.calls) if self.calls else 0.0
