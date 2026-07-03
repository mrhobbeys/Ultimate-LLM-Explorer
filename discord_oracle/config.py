"""Runtime configuration for the Oracle cog. Everything has a sane default so
the bot runs with zero configuration; an Anthropic key unlocks the LLM oracle."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Loaded once at import from the environment."""

    db_path: Path
    discord_token: str | None
    command_prefix: str
    anthropic_api_key: str | None
    model: str
    llm_max_tokens: int
    hostname: str

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @classmethod
    def load(cls) -> "Config":
        root = Path(__file__).resolve().parent
        default_db = root / "data" / "oracle.db"
        db_path = Path(os.environ.get("ORACLE_DB", str(default_db))).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return cls(
            db_path=db_path,
            discord_token=os.environ.get("DISCORD_TOKEN"),
            command_prefix=os.environ.get("ORACLE_PREFIX", "!"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            # Default to the most capable widely-available Opus tier. Override
            # with ORACLE_MODEL (e.g. claude-haiku-4-5 for cheaper NPC chatter).
            model=os.environ.get("ORACLE_MODEL", "claude-opus-4-8"),
            llm_max_tokens=int(os.environ.get("ORACLE_LLM_MAX_TOKENS", "1024")),
            hostname=os.environ.get("ORACLE_HOSTNAME", "MERIDIAN-DC01"),
        )


config = Config.load()
