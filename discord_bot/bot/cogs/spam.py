"""Spam protection: rate, duplicate, and per-message flood limits.

All cheap, deterministic, in-memory — no LLM, no disk. When a limit trips we
hand off to the Moderation cog's ``enforce`` so mode (shadow/approve/armed),
logging and metrics are handled in one place.
"""

from __future__ import annotations

import discord
from discord.ext import commands, tasks

from ..analysis import CUSTOM_EMOJI_RE, MENTION_RE, URL_RE, _emoji_count
from ..ratelimit import DuplicateTracker, SlidingWindow


class Spam(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cfg = bot.cfg.spam
        self.rate = SlidingWindow(self.cfg.max_messages, self.cfg.window_seconds)
        self.dupes = DuplicateTracker(self.cfg.duplicate_limit, self.cfg.duplicate_window)
        self._prune.start()

    def cog_unload(self) -> None:
        self._prune.cancel()

    @tasks.loop(minutes=5)
    async def _prune(self) -> None:
        # keep the in-memory windows from accumulating idle users
        self.rate.prune()

    def _gi(self, gid, key, default):
        return self.bot.settings.get_int(gid, key, default)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        perms = getattr(message.author, "guild_permissions", None)
        if perms and (perms.manage_messages or perms.administrator):
            return
        gid = message.guild.id
        if self.bot.settings.get_bool(gid, "enforce.paused", False):
            return
        key = message.author.id
        content = message.content or ""

        reason = None
        # rate flood
        if self.rate.over_limit(key):
            reason = "message rate flood"
        # duplicate spam
        elif content and self.dupes.over_limit(key, content):
            reason = "duplicate spam"
        else:
            mentions = len(MENTION_RE.findall(content))
            links = len(URL_RE.findall(content))
            emoji = _emoji_count(content) + len(CUSTOM_EMOJI_RE.findall(content))
            newlines = content.count("\n")
            if mentions > self._gi(gid, "spam.max_mentions", self.cfg.max_mentions):
                reason = f"mention flood ({mentions})"
            elif links > self._gi(gid, "spam.max_links", self.cfg.max_links):
                reason = f"link flood ({links})"
            elif emoji > self._gi(gid, "spam.max_emoji", self.cfg.max_emoji):
                reason = f"emoji flood ({emoji})"
            elif newlines > self._gi(gid, "spam.max_newlines", self.cfg.max_newlines):
                reason = f"newline flood ({newlines})"

        if reason is None:
            return

        self.bot.metrics.spam_trips += 1
        mod = self.bot.get_cog("Moderation")
        action = self.bot.settings.get_str(gid, "spam.action", self.cfg.action)
        if mod is not None:
            await mod.enforce(  # type: ignore[attr-defined]
                message, kind="spam", action=action, reason=reason, severity=0.5
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Spam(bot))
