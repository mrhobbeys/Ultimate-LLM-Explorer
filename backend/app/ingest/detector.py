"""Sniff which adapter to use for a given file or folder.

Strategy:
- Walk directories, yielding each candidate file.
- For each file, check adapters in order; the first ``sniff`` win matches.

Adapters are imported lazily to avoid circular imports.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


def iter_sources(path: Path) -> Iterator[Path]:
    """Yield files worth sniffing from ``path``. Skips hidden and vendor dirs."""
    if path.is_file():
        yield path
        return
    for p in path.rglob("*"):
        if not p.is_file():
            continue
        if any(part.startswith(".") for part in p.relative_to(path).parts):
            continue
        if p.suffix.lower() in {".json", ".html", ".htm"}:
            yield p


def detect(path: Path) -> str | None:
    """Return the adapter name that claims ``path``, or ``None``."""
    # Local import to break the cycle with the package __init__.
    from . import ADAPTERS

    for name, adapter in ADAPTERS.items():
        try:
            if adapter.sniff(path):
                return name
        except Exception:  # defensive; sniff must be cheap and tolerant
            continue
    return None
