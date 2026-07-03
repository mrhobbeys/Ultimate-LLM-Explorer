"""Record-keeping cog: mirror server activity to a log channel + SQLite.

Two sinks:
  * a Discord channel (set LOG_CHANNEL_ID) for humans to skim
  * the ``message_log`` / ``mod_events`` SQLite tables for durable history

The message firehose (LOG_MESSAGES) is off by default because storing every
message is the single most expensive thing you can ask a Pi's SD card to do.
Edits, deletes, joins and leaves are cheap and on by default.
"""

from __future__ import annotations

import time

import discord
from discord.ext import commands, tasks


class Logging(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cfg = bot.cfg.logging
        self._prune_retention.start()

    def cog_unload(self) -> None:
        self._prune_retention.cancel()

    @tasks.loop(hours=24)
    async def _prune_retention(self) -> None:
        days = self.cfg.retention_days
        if days <= 0:
            return
        cutoff = time.time() - days * 86400
        await self.bot.db.execute("DELETE FROM message_log WHERE ts < ?", (cutoff,))

    # -- helpers ----------------------------------------------------------- #
    def _channel(self, guild: discord.Guild | None) -> discord.abc.Messageable | None:
        gid = guild.id if guild else None
        # per-guild override wins over the global default
        cid = self.bot.settings.get_int(gid, "log.channel", self.cfg.log_channel_id or 0)
        if not cid:
            return None
        ch = self.bot.get_channel(cid)
        return ch if isinstance(ch, discord.abc.Messageable) else None

    def _log_messages(self, guild: discord.Guild | None) -> bool:
        gid = guild.id if guild else None
        return self.bot.settings.get_bool(gid, "log.messages", self.cfg.log_messages)

    async def _send(self, guild: discord.Guild | None, embed: discord.Embed) -> None:
        ch = self._channel(guild)
        if ch is None:
            return
        try:
            await ch.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _store(
        self, *, guild_id, channel_id, user_id, message_id, kind, content
    ) -> None:
        await self.bot.db.execute(
            "INSERT INTO message_log "
            "(guild_id, channel_id, user_id, message_id, kind, content, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, user_id, message_id, kind, (content or "")[:1900], time.time()),
        )

    # -- public: called by the moderation pipeline ------------------------- #
    async def emit_mod(
        self, *, guild_id, user_id, channel_id, kind, action, reason, severity
    ) -> None:
        if not (self.cfg.enabled and self.cfg.log_moderation):
            return
        guild = self.bot.get_guild(guild_id) if guild_id else None
        color = discord.Color.orange() if action in {"warn", "log", "shadow"} else discord.Color.red()
        embed = discord.Embed(title=f"Moderation · {kind}", color=color)
        embed.add_field(name="Action", value=action, inline=True)
        embed.add_field(name="Severity", value=f"{severity:.2f}", inline=True)
        if user_id:
            embed.add_field(name="User", value=f"<@{user_id}>", inline=True)
        if channel_id:
            embed.add_field(name="Channel", value=f"<#{channel_id}>", inline=True)
        embed.description = reason or "—"
        await self._send(guild, embed)

    # -- listeners --------------------------------------------------------- #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self.cfg.enabled or message.author.bot or message.guild is None:
            return
        if not self._log_messages(message.guild):
            return
        await self._store(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            message_id=message.id,
            kind="create",
            content=message.content,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not (self.cfg.enabled and self.cfg.log_edits):
            return
        if before.author.bot or before.guild is None or before.content == after.content:
            return
        await self._store(
            guild_id=before.guild.id,
            channel_id=before.channel.id,
            user_id=before.author.id,
            message_id=before.id,
            kind="edit",
            content=after.content,
        )
        embed = discord.Embed(title="Message edited", color=discord.Color.gold())
        embed.add_field(name="Author", value=before.author.mention, inline=True)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Before", value=(before.content or "—")[:1000], inline=False)
        embed.add_field(name="After", value=(after.content or "—")[:1000], inline=False)
        await self._send(before.guild, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not (self.cfg.enabled and self.cfg.log_deletes):
            return
        if message.author.bot or message.guild is None:
            return
        await self._store(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            message_id=message.id,
            kind="delete",
            content=message.content,
        )
        embed = discord.Embed(title="Message deleted", color=discord.Color.dark_red())
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.description = (message.content or "—")[:1500]
        await self._send(message.guild, embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not (self.cfg.enabled and self.cfg.log_joins):
            return
        embed = discord.Embed(title="Member joined", color=discord.Color.green())
        embed.description = f"{member.mention} ({member})"
        created = int(member.created_at.timestamp())
        embed.add_field(name="Account created", value=f"<t:{created}:R>", inline=True)
        await self._send(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not (self.cfg.enabled and self.cfg.log_leaves):
            return
        embed = discord.Embed(title="Member left", color=discord.Color.dark_grey())
        embed.description = f"{member} ({member.id})"
        await self._send(member.guild, embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Logging(bot))
