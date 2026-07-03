"""A compact, self-describing help command (we disabled the built-in one)."""

from __future__ import annotations

import discord
from discord.ext import commands

SECTIONS = {
    "General": [
        ("help", "Show this message"),
        ("ping", "Bot + gateway latency"),
        ("search <flags>", "Build a Discord search string"),
        ("searchhelp", "Explain Discord search operators"),
    ],
    "Ranking": [
        ("rank [@user]", "Show level, XP, rep, badges"),
        ("leaderboard", "Top 10 by XP"),
        ("rep @user", "Give someone a reputation point"),
    ],
    "Moderation (staff)": [
        ("mod", "Show moderation status"),
        ("mod mode <off|shadow|approve|armed>", "Set enforcement mode"),
        ("mod sensitivity <0-1>", "One dial to tune strictness"),
        ("mod test <text>", "Dry-run the analyzer"),
        ("warn @user [reason]", "Warn a user (escalation ladder)"),
        ("warnings [@user]", "List warnings"),
    ],
    "Admin (owner/admins)": [
        ("setup", "Guided onboarding wizard"),
        ("set <key> <value>", "Change a setting live"),
        ("get [key]", "Show settings"),
        ("backup", "Back up the database now"),
        ("health", "Live Pi health + bot metrics"),
    ],
    "Explore (discord.py)": [
        ("inspect <thing>", "Inspect a member/channel/guild"),
        ("tail [#channel]", "Live-mirror messages here (owner)"),
        ("gateway", "Shards, latency, cache sizes"),
        ("reload <cog>", "Hot-reload a cog (owner)"),
    ],
}


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="help")
    async def help(self, ctx: commands.Context, *, topic: str = "") -> None:
        p = ctx.prefix
        embed = discord.Embed(
            title="🤖 Bot help",
            description=f"Prefix: `{p}` — you can also @mention me.",
            color=discord.Color.blurple(),
        )
        for section, cmds in SECTIONS.items():
            value = "\n".join(f"`{p}{name}` — {desc}" for name, desc in cmds)
            embed.add_field(name=section, value=value, inline=False)
        embed.set_footer(text="Made to run on a Raspberry Pi. Be gentle. 🍓")
        await ctx.send(embed=embed)

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context) -> None:
        ms = round(self.bot.latency * 1000)
        lag = round(self.bot.metrics.lag.last_lag_ms)
        await ctx.send(f"🏓 Gateway `{ms}ms` · event-loop lag `{lag}ms`")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
