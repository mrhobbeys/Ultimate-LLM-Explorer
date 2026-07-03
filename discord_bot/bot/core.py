"""The Bot subclass that wires config, storage, analysis and LLM together."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .analysis import TextAnalyzer
from .bayes import BayesFilter
from .config import Config
from .db import Database
from .llm import LLMClient
from .metrics import Metrics
from .settings import Settings
from .webadmin import WebAdmin

log = logging.getLogger("bot")

# Cogs are loaded in this order. Each is a module under bot.cogs.
COGS = [
    "bot.cogs.logs",
    "bot.cogs.spam",
    "bot.cogs.moderation",
    "bot.cogs.remote",
    "bot.cogs.raid",
    "bot.cogs.ranking",
    "bot.cogs.search",
    "bot.cogs.helpcog",
    "bot.cogs.explore",
    "bot.cogs.health",
    "bot.cogs.admin",
]


def build_intents(cfg: Config) -> discord.Intents:
    intents = discord.Intents.default()
    # message_content is a *privileged* intent — enable it in the Developer
    # Portal for your application, or the bot can't read message text.
    intents.message_content = True
    intents.members = True   # needed for join/leave logging and member lookups
    return intents


class PiBot(commands.Bot):
    def __init__(self, cfg: Config) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or(cfg.prefix),
            intents=build_intents(cfg),
            help_command=None,  # we ship our own in helpcog
            case_insensitive=True,
            max_messages=1000,  # cap the message cache — RAM matters on a Pi
            owner_ids=set(cfg.owner_ids) if cfg.owner_ids else None,
        )
        self.cfg = cfg
        self.db = Database(cfg.db_path)
        self.settings = Settings(self)
        self.analyzer = TextAnalyzer(
            enable_nltk=cfg.enable_nltk,
            wordlist_path=cfg.profanity_wordlist,
        )
        self.llm = LLMClient(cfg.llm, cache_size=cfg.moderation.verdict_cache_size)
        self.bayes = BayesFilter(cfg.bayes, self.db)
        self.metrics = Metrics(self)
        self.webadmin = WebAdmin(self)

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.settings.load()
        await self.bayes.load()
        await self.llm.start()
        if self.cfg.metrics.enabled:
            await self.metrics.start_http(self.cfg.metrics.host, self.cfg.metrics.port)
        await self.webadmin.start()
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info("loaded %s", ext)
            except Exception:  # noqa: BLE001
                log.exception("failed to load %s", ext)

    async def on_ready(self) -> None:
        log.info("logged in as %s (id=%s)", self.user, getattr(self.user, "id", "?"))
        log.info(
            "guilds=%d nltk=%s llm=%s mode=%s",
            len(self.guilds),
            self.analyzer.nltk_active,
            self.cfg.llm.enabled,
            self.cfg.moderation.mode,
        )
        if self.cfg.mailer.notify_on_start:
            from .mailer import send

            await send(
                self.cfg.mailer,
                "Pi bot started",
                f"Logged in as {self.user} across {len(self.guilds)} guild(s).",
            )

    async def close(self) -> None:
        await self.webadmin.stop()
        await self.metrics.stop()
        await self.llm.close()
        await self.db.close()
        await super().close()

    async def log_mod_event(
        self,
        *,
        guild_id: int | None,
        user_id: int | None,
        channel_id: int | None,
        kind: str,
        action: str,
        reason: str,
        severity: float,
    ) -> None:
        import time

        await self.db.execute(
            "INSERT INTO mod_events "
            "(guild_id, user_id, channel_id, kind, action, reason, severity, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, channel_id, kind, action, reason, severity, time.time()),
        )
        cog = self.get_cog("Logging")
        if cog is not None:
            await cog.emit_mod(  # type: ignore[attr-defined]
                guild_id=guild_id,
                user_id=user_id,
                channel_id=channel_id,
                kind=kind,
                action=action,
                reason=reason,
                severity=severity,
            )
