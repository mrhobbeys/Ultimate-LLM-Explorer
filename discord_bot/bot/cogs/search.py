"""Advanced-search assistant.

Discord's search bar supports powerful operators most people never learn:
``from:`` ``mentions:`` ``has:`` ``before:`` ``after:`` ``during:`` ``in:``
``pinned:``. This cog teaches them and, given friendly flags, emits the exact
string to paste into the search box (resolving #channel and @user mentions to
the names the search bar expects).
"""

from __future__ import annotations

import re

import discord
from discord.ext import commands

HAS_VALUES = {"link", "embed", "file", "video", "image", "sound", "sticker"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CHANNEL_MENTION = re.compile(r"<#(\d+)>")
USER_MENTION = re.compile(r"<@!?(\d+)>")


def build_query(bot: commands.Bot, guild: discord.Guild | None, tokens: list[str]) -> tuple[str, list[str]]:
    """Return (query_string, warnings)."""
    parts: list[str] = []
    words: list[str] = []
    warnings: list[str] = []

    def resolve_channel(val: str) -> str:
        m = CHANNEL_MENTION.match(val)
        if m and guild:
            ch = guild.get_channel(int(m.group(1)))
            if ch:
                return ch.name
        return val.lstrip("#")

    def resolve_user(val: str) -> str:
        m = USER_MENTION.match(val)
        if m:
            user = bot.get_user(int(m.group(1)))
            if user:
                return user.name
        return val.lstrip("@")

    for tok in tokens:
        low = tok.lower()
        if low.startswith(("from:", "mentions:", "to:")):
            key, _, val = tok.partition(":")
            key = "mentions" if key.lower() in {"mentions", "to"} else "from"
            parts.append(f"{key}:{resolve_user(val)}")
        elif low.startswith("in:"):
            parts.append(f"in:{resolve_channel(tok.partition(':')[2])}")
        elif low.startswith("has:"):
            val = low.partition(":")[2]
            if val not in HAS_VALUES:
                warnings.append(f"`has:{val}` isn't valid; use one of {sorted(HAS_VALUES)}.")
            else:
                parts.append(f"has:{val}")
        elif low.startswith(("before:", "after:", "during:")):
            key, _, val = tok.partition(":")
            if not DATE_RE.match(val):
                warnings.append(f"`{key}:` wants YYYY-MM-DD (got `{val}`).")
            parts.append(f"{key.lower()}:{val}")
        elif low in {"pinned", "pinned:true"}:
            parts.append("pinned:true")
        else:
            words.append(tok)

    query = " ".join(parts + words).strip()
    return query, warnings


class Search(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="search")
    async def search(self, ctx: commands.Context, *, args: str = "") -> None:
        """Build a Discord search string. Example:
        `!search from:@bob in:#general has:link before:2024-01-01 raspberry pi`
        """
        if not args.strip():
            await self.searchhelp(ctx)
            return
        tokens = args.split()
        query, warnings = build_query(self.bot, ctx.guild, tokens)
        embed = discord.Embed(
            title="🔍 Paste this into Discord's search box",
            description=f"```\n{query}\n```",
            color=discord.Color.teal(),
        )
        if warnings:
            embed.add_field(name="⚠️ Heads up", value="\n".join(warnings), inline=False)
        embed.set_footer(text="Tip: press Ctrl/Cmd+F in Discord to open search.")
        await ctx.send(embed=embed)

    @commands.command(name="searchhelp", aliases=["shelp"])
    async def searchhelp(self, ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="🔍 Discord search operators",
            color=discord.Color.teal(),
            description=(
                "Combine these in the search bar (Ctrl/Cmd+F):\n\n"
                "`from:user` — messages by someone\n"
                "`mentions:user` — messages that ping someone\n"
                "`in:channel` — restrict to a channel\n"
                "`has:link|embed|file|video|image|sound|sticker`\n"
                "`before:YYYY-MM-DD` · `after:YYYY-MM-DD` · `during:YYYY-MM-DD`\n"
                "`pinned:true` — only pinned messages\n\n"
                "**Example**\n"
                "`from:bob in:general has:image after:2024-01-01 sunset`\n\n"
                f"Let me build one for you: `{ctx.prefix}search from:@you has:link cats`"
            ),
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Search(bot))
