"""Remote admin console — run the server from your DMs.

An admin (bot owner, a member with ban/manage perms, or anyone holding the
configured ``admin.role``) can DM the bot and:

  * ``guilds``            list servers you may administer
  * ``use <guild>``       pick the active server for this DM session
  * ``users [query]``     list members (optionally filtered)
  * ``recent @user [n]``  pull a member's recent messages (needs message logging)
  * ``ban/kick/timeout``  moderate a member
  * ``delete <ch> <id>``  delete a specific message
  * ``purge <ch> <n>``    bulk-delete recent messages
  * ``say <ch> <text>``   speak as the bot

Every one of these also works typed inside a server channel — the guild is just
resolved from context there instead of the ``use`` selection. Permission is
checked against the *target* guild on every call, so DMing the bot grants no
power you don't already have in that server.
"""

from __future__ import annotations

import datetime

import discord
from discord.ext import commands


def _is_owner(bot: commands.Bot, uid: int) -> bool:
    return uid in (bot.owner_ids or set()) or uid == getattr(bot, "owner_id", None)


async def resolve_member(guild: discord.Guild, ident: str) -> discord.Member | None:
    ident = ident.strip().strip("<@!>")
    if ident.isdigit():
        member = guild.get_member(int(ident))
        if member:
            return member
        try:
            return await guild.fetch_member(int(ident))
        except discord.HTTPException:
            return None
    ident_low = ident.lower()
    for m in guild.members:
        if ident_low in (m.name.lower(), (m.display_name or "").lower()):
            return m
    return None


class RemoteAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # per-user active guild for DM sessions
        self._active: dict[int, int] = {}

    # -- permission + guild resolution ------------------------------------- #
    async def is_admin(self, guild: discord.Guild, user_id: int) -> bool:
        if _is_owner(self.bot, user_id):
            return True
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return False
        perms = member.guild_permissions
        if perms.administrator or perms.ban_members or perms.manage_guild:
            return True
        role_id = self.bot.settings.get_int(guild.id, "admin.role", 0)
        return bool(role_id) and any(r.id == role_id for r in member.roles)

    async def target_guild(self, ctx: commands.Context) -> discord.Guild | None:
        if ctx.guild is not None:
            return ctx.guild
        gid = self._active.get(ctx.author.id)
        return self.bot.get_guild(gid) if gid else None

    async def guard(self, ctx: commands.Context) -> discord.Guild | None:
        """Resolve the target guild and verify the caller may admin it."""
        guild = await self.target_guild(ctx)
        if guild is None:
            await ctx.send(
                "No active server. DM me `guilds` then `use <id>` to pick one."
            )
            return None
        if not await self.is_admin(guild, ctx.author.id):
            await ctx.send("⛔ You don't have admin rights in that server.")
            return None
        return guild

    # -- session ----------------------------------------------------------- #
    @commands.command(name="guilds", aliases=["servers"])
    async def guilds(self, ctx: commands.Context) -> None:
        rows = []
        for g in self.bot.guilds:
            if await self.is_admin(g, ctx.author.id):
                rows.append(f"`{g.id}` — {g.name} ({g.member_count} members)")
        if not rows:
            await ctx.send("You don't administer any servers I'm in.")
            return
        await ctx.send("**Servers you can manage:**\n" + "\n".join(rows[:25]))

    @commands.command(name="use")
    async def use(self, ctx: commands.Context, *, ident: str) -> None:
        ident = ident.strip()
        guild = None
        if ident.isdigit():
            guild = self.bot.get_guild(int(ident))
        if guild is None:
            for g in self.bot.guilds:
                if g.name.lower() == ident.lower():
                    guild = g
                    break
        if guild is None:
            await ctx.send("Couldn't find that server. Use `guilds` for the list.")
            return
        if not await self.is_admin(guild, ctx.author.id):
            await ctx.send("⛔ You don't have admin rights there.")
            return
        self._active[ctx.author.id] = guild.id
        await ctx.send(f"✅ Active server set to **{guild.name}**.")

    # -- inspection -------------------------------------------------------- #
    @commands.command(name="users", aliases=["members"])
    async def users(self, ctx: commands.Context, *, query: str = "") -> None:
        guild = await self.guard(ctx)
        if guild is None:
            return
        q = query.lower().strip()
        members = [
            m for m in guild.members
            if not q or q in m.name.lower() or q in (m.display_name or "").lower()
        ]
        members.sort(key=lambda m: (m.joined_at or datetime.datetime.max.replace(
            tzinfo=datetime.timezone.utc)))
        lines = [
            f"`{m.id}` {m} {'🤖' if m.bot else ''}".rstrip()
            for m in members[:30]
        ]
        header = f"**{len(members)} member(s)**" + (f" matching `{q}`" if q else "")
        await ctx.send(header + "\n" + "\n".join(lines) if lines else f"{header}\n(none)")

    @commands.command(name="recent", aliases=["history"])
    async def recent(self, ctx: commands.Context, ident: str, n: int = 10) -> None:
        guild = await self.guard(ctx)
        if guild is None:
            return
        member = await resolve_member(guild, ident)
        if member is None:
            await ctx.send("User not found. Pass a mention, id, or name.")
            return
        n = max(1, min(50, n))
        rows = await self.bot.db.fetchall(
            "SELECT channel_id, kind, content, ts FROM message_log "
            "WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT ?",
            (guild.id, member.id, n),
        )
        if not rows:
            await ctx.send(
                f"No logged messages for {member}. Enable logging with "
                "`set log.messages true` to capture history going forward."
            )
            return
        lines = []
        for r in rows:
            when = f"<t:{int(r['ts'])}:R>" if ctx.guild else datetime.datetime.utcfromtimestamp(
                r["ts"]).strftime("%m-%d %H:%M")
            lines.append(f"[{r['kind']}] {when} #{r['channel_id']}: {(r['content'] or '')[:150]}")
        text = f"**Recent from {member}:**\n" + "\n".join(lines)
        await ctx.send(text[:1900])

    # -- moderation actions ------------------------------------------------ #
    @commands.command(name="ban")
    async def ban(self, ctx: commands.Context, ident: str, *, reason: str = "via remote admin") -> None:
        guild = await self.guard(ctx)
        if guild is None:
            return
        member = await resolve_member(guild, ident)
        target = member or (int(ident) if ident.strip().isdigit() else None)
        try:
            if member is not None:
                await guild.ban(member, reason=reason, delete_message_seconds=0)
            elif target is not None:
                await guild.ban(discord.Object(id=target), reason=reason)
            else:
                await ctx.send("User not found.")
                return
        except discord.Forbidden:
            await ctx.send("⛔ I lack permission to ban them (role hierarchy?).")
            return
        await self._audit(guild, ctx.author, "ban", ident, reason)
        await ctx.send(f"🔨 Banned `{ident}`. Reason: {reason}")

    @commands.command(name="kick")
    async def kick(self, ctx: commands.Context, ident: str, *, reason: str = "via remote admin") -> None:
        guild = await self.guard(ctx)
        if guild is None:
            return
        member = await resolve_member(guild, ident)
        if member is None:
            await ctx.send("User not found.")
            return
        try:
            await member.kick(reason=reason)
        except discord.Forbidden:
            await ctx.send("⛔ I lack permission to kick them.")
            return
        await self._audit(guild, ctx.author, "kick", ident, reason)
        await ctx.send(f"👢 Kicked {member}. Reason: {reason}")

    @commands.command(name="timeout", aliases=["mute"])
    async def timeout(
        self, ctx: commands.Context, ident: str, minutes: int = 10, *, reason: str = "via remote admin"
    ) -> None:
        guild = await self.guard(ctx)
        if guild is None:
            return
        member = await resolve_member(guild, ident)
        if member is None:
            await ctx.send("User not found.")
            return
        until = discord.utils.utcnow() + datetime.timedelta(minutes=max(1, minutes))
        try:
            await member.timeout(until, reason=reason)
        except discord.Forbidden:
            await ctx.send("⛔ I lack permission to timeout them.")
            return
        await self._audit(guild, ctx.author, "timeout", ident, f"{minutes}m: {reason}")
        await ctx.send(f"⏳ Timed out {member} for {minutes} min.")

    @commands.command(name="delete", aliases=["del"])
    async def delete(self, ctx: commands.Context, channel_id: int, message_id: int) -> None:
        guild = await self.guard(ctx)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            await ctx.send("Channel not found.")
            return
        try:
            msg = await channel.fetch_message(message_id)
            await msg.delete()
        except discord.HTTPException:
            await ctx.send("Couldn't delete that message.")
            return
        await self._audit(guild, ctx.author, "delete", str(message_id), "")
        await ctx.send("🗑️ Deleted.")

    @commands.command(name="purge", aliases=["clear"])
    async def purge(self, ctx: commands.Context, channel_id: int, n: int) -> None:
        guild = await self.guard(ctx)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await ctx.send("Text channel not found.")
            return
        n = max(1, min(100, n))
        try:
            deleted = await channel.purge(limit=n)
        except discord.HTTPException:
            await ctx.send("Couldn't purge (need Manage Messages).")
            return
        await self._audit(guild, ctx.author, "purge", str(channel_id), f"{len(deleted)} msgs")
        await ctx.send(f"🧹 Purged {len(deleted)} messages from #{channel.name}.")

    @commands.command(name="say")
    async def say(self, ctx: commands.Context, channel_id: int, *, text: str) -> None:
        guild = await self.guard(ctx)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            await ctx.send("Channel not found.")
            return
        await channel.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())
        await ctx.send("📣 Sent.")

    async def _audit(self, guild, author, action, target, reason) -> None:
        await self.bot.log_mod_event(
            guild_id=guild.id,
            user_id=None,
            channel_id=None,
            kind="remote",
            action=action,
            reason=f"by {author} → {target} · {reason}",
            severity=0.5,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RemoteAdmin(bot))
