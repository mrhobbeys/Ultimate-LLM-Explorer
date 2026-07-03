"""Exploration tools for learning discord.py and watching the server live.

  * ``tail``     — mirror messages from a channel into the current one, live
                   ("see what people are typing now"). Owner-only, auto-expires.
  * ``inspect``  — dump the attributes of a member/channel/guild/role.
  * ``gateway``  — latency, shard, intents and cache-size introspection.
  * ``reload``   — hot-reload a cog while the bot runs (owner-only).
"""

from __future__ import annotations

import io
import time

import discord
from discord.ext import commands


class Explore(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # {source_channel_id: (dest_channel_id, expires_at)}
        self._tails: dict[int, tuple[int, float]] = {}

    # -- live firehose ----------------------------------------------------- #
    @commands.command(name="tail")
    @commands.is_owner()
    async def tail(
        self, ctx: commands.Context, channel: discord.TextChannel | None = None, minutes: int = 10
    ) -> None:
        """Mirror a channel's messages into here for N minutes (default 10)."""
        source = channel or ctx.channel
        if source.id in self._tails:
            del self._tails[source.id]
            await ctx.send(f"Stopped tailing {source.mention}.")
            return
        self._tails[source.id] = (ctx.channel.id, time.time() + minutes * 60)
        await ctx.send(f"👀 Tailing {source.mention} for {minutes} min. Run again to stop.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not self._tails:
            return
        entry = self._tails.get(message.channel.id)
        if entry is None:
            return
        dest_id, expires = entry
        if time.time() > expires:
            del self._tails[message.channel.id]
            return
        dest = self.bot.get_channel(dest_id)
        if dest is None or dest.id == message.channel.id:
            return
        content = message.content or "*(no text)*"
        try:
            await dest.send(
                f"`{message.author}` in {message.channel.mention}: {content[:1500]}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass

    # -- introspection ----------------------------------------------------- #
    @commands.command(name="inspect")
    @commands.is_owner()
    async def inspect(self, ctx: commands.Context, *, target: str = "") -> None:
        """Inspect a member/channel/role/guild by mention, id, or 'guild'."""
        obj: object = ctx.guild
        target = target.strip()
        if target in {"", "guild", "server"}:
            obj = ctx.guild
        elif ctx.message.mentions:
            obj = ctx.message.mentions[0]
        elif ctx.message.channel_mentions:
            obj = ctx.message.channel_mentions[0]
        elif ctx.message.role_mentions:
            obj = ctx.message.role_mentions[0]
        elif target.isdigit():
            oid = int(target)
            obj = (
                ctx.guild.get_member(oid)
                or ctx.guild.get_channel(oid)
                or ctx.guild.get_role(oid)
                or ctx.guild
            )
        lines = []
        for attr in sorted(dir(obj)):
            if attr.startswith("_"):
                continue
            try:
                val = getattr(obj, attr)
            except Exception:
                continue
            if callable(val):
                continue
            sval = repr(val)
            if len(sval) > 120:
                sval = sval[:117] + "..."
            lines.append(f"{attr} = {sval}")
        text = f"# {type(obj).__name__}\n" + "\n".join(lines)
        if len(text) < 1900:
            await ctx.send(f"```py\n{text}\n```")
        else:
            await ctx.send(
                file=discord.File(io.BytesIO(text.encode()), filename="inspect.txt")
            )

    @commands.command(name="gateway", aliases=["gw"])
    @commands.is_owner()
    async def gateway(self, ctx: commands.Context) -> None:
        b = self.bot
        intents = [n for n, v in b.intents if v]
        embed = discord.Embed(title="🛰️ Gateway", color=discord.Color.dark_teal())
        embed.add_field(name="Latency", value=f"{round(b.latency*1000)} ms", inline=True)
        embed.add_field(name="Guilds", value=str(len(b.guilds)), inline=True)
        embed.add_field(name="Users (cached)", value=str(len(b.users)), inline=True)
        embed.add_field(name="Cached messages", value=str(len(b.cached_messages)), inline=True)
        embed.add_field(name="Shards", value=str(b.shard_count or 1), inline=True)
        embed.add_field(name="Intents", value=", ".join(intents)[:1000] or "—", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="reload")
    @commands.is_owner()
    async def reload(self, ctx: commands.Context, cog: str) -> None:
        ext = cog if cog.startswith("bot.cogs.") else f"bot.cogs.{cog}"
        try:
            await self.bot.reload_extension(ext)
            await ctx.send(f"🔄 Reloaded `{ext}`.")
        except Exception as exc:  # noqa: BLE001
            await ctx.send(f"❌ `{type(exc).__name__}`: {exc}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Explore(bot))
