"""Standalone runnable bot. `python -m discord_oracle.bot`.

Needs only DISCORD_TOKEN in the environment. No LLM key required — the game runs
fully on the deterministic engine. Set ANTHROPIC_API_KEY (paid) or point
ORACLE_LLM_BACKEND=ollama at a local model (free) to enrich NPC conversations.
"""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

from .config import config


def build_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True  # required to read the immersive session input
    bot = commands.Bot(command_prefix=config.command_prefix, intents=intents)

    @bot.event
    async def on_ready() -> None:
        print(f"Oracle online as {bot.user} — prefix '{config.command_prefix}'")

    return bot


async def _main() -> None:
    if not config.discord_token:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Export it (see .env.example) and retry."
        )
    bot = build_bot()
    from .cog import setup as cog_setup

    await cog_setup(bot)
    async with bot:
        await bot.start(config.discord_token)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
