"""Adapter protocol. Each provider implements :meth:`parse` to yield
canonical ``Conversation`` records from a single source file or directory."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import Conversation


@dataclass
class IngestContext:
    source: Path
    raw_ref: str | None = None
    errors: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)


@runtime_checkable
class Adapter(Protocol):
    name: str

    def sniff(self, path: Path) -> bool: ...

    def parse(self, path: Path, ctx: IngestContext) -> Iterator[Conversation]: ...
