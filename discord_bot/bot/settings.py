"""Per-guild settings overlay — the multi-tenant backbone.

One bot process can serve many servers, each with its own knobs, without a
process per customer (that's the whole hosting-economics point). Every cog
reads its effective config through this overlay:

    value = bot.settings.get_int(guild_id, "spam.max_messages",
                                 bot.cfg.spam.max_messages)

If the guild has no override, the global :class:`Config` default is used. All
overrides live in the ``guild_settings`` table and are cached in memory, so
reads are free and only writes hit the disk.
"""

from __future__ import annotations

from typing import Any


class Settings:
    def __init__(self, bot) -> None:
        self.bot = bot
        # {guild_id: {key: value_str}}
        self._cache: dict[int, dict[str, str]] = {}

    async def load(self) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT guild_id, key, value FROM guild_settings"
        )
        for row in rows:
            self._cache.setdefault(row["guild_id"], {})[row["key"]] = row["value"]

    # -- raw ---------------------------------------------------------------- #
    def _raw(self, guild_id: int | None, key: str) -> str | None:
        if guild_id is None:
            return None
        return self._cache.get(guild_id, {}).get(key)

    async def set(self, guild_id: int, key: str, value: Any) -> None:
        sval = str(value)
        self._cache.setdefault(guild_id, {})[key] = sval
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (guild_id, key, sval),
        )

    async def unset(self, guild_id: int, key: str) -> None:
        self._cache.get(guild_id, {}).pop(key, None)
        await self.bot.db.execute(
            "DELETE FROM guild_settings WHERE guild_id=? AND key=?", (guild_id, key)
        )

    def all_for(self, guild_id: int) -> dict[str, str]:
        return dict(self._cache.get(guild_id, {}))

    # -- typed getters ------------------------------------------------------ #
    def get_str(self, guild_id: int | None, key: str, default: str) -> str:
        raw = self._raw(guild_id, key)
        return raw if raw is not None else default

    def get_int(self, guild_id: int | None, key: str, default: int) -> int:
        raw = self._raw(guild_id, key)
        if raw is None:
            return default
        try:
            return int(float(raw))
        except ValueError:
            return default

    def get_float(self, guild_id: int | None, key: str, default: float) -> float:
        raw = self._raw(guild_id, key)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def get_bool(self, guild_id: int | None, key: str, default: bool) -> bool:
        raw = self._raw(guild_id, key)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on", "y"}
