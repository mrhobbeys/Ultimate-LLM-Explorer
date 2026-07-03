"""Tiny in-memory sliding-window counters for spam detection.

Deque-based, no dependencies. Memory is bounded by pruning old timestamps on
every touch, and we drop empty user entries so idle members cost nothing —
important when RAM is measured in megabytes.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindow:
    """Counts events per key within a rolling time window."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def hit(self, key: int, now: float | None = None) -> int:
        """Record an event and return the current count in the window."""
        now = time.monotonic() if now is None else now
        dq = self._events[key]
        dq.append(now)
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if not dq:
            del self._events[key]
            return 0
        return len(dq)

    def over_limit(self, key: int, now: float | None = None) -> bool:
        return self.hit(key, now) > self.limit

    def prune(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        for key in list(self._events):
            dq = self._events[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                del self._events[key]


class DuplicateTracker:
    """Detects the same content repeated by a user within a window."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        # key -> deque[(timestamp, content_hash)]
        self._seen: dict[int, deque[tuple[float, int]]] = defaultdict(deque)

    def add(self, key: int, content: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        h = hash(content.strip().lower())
        dq = self._seen[key]
        dq.append((now, h))
        cutoff = now - self.window
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        count = sum(1 for _, hh in dq if hh == h)
        if not dq:
            del self._seen[key]
        return count

    def over_limit(self, key: int, content: str, now: float | None = None) -> bool:
        return self.add(key, content, now) >= self.limit
