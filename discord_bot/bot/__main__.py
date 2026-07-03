"""Entrypoint: ``python -m bot``."""

from __future__ import annotations

import logging
import sys

import discord

from .config import Config
from .core import PiBot


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = Config.load()
    if not cfg.token:
        print(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.",
            file=sys.stderr,
        )
        return 2

    bot = PiBot(cfg)
    try:
        bot.run(cfg.token, log_handler=None)  # we configured logging ourselves
    except discord.LoginFailure:
        print("Login failed: check DISCORD_TOKEN.", file=sys.stderr)
        return 1
    except discord.PrivilegedIntentsRequired:
        print(
            "Privileged intents required. Enable MESSAGE CONTENT and SERVER "
            "MEMBERS intents in the Discord Developer Portal for this app.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
