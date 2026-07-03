"""Raid & scam defense + the warning escalation ladder.

  * Join-velocity raid detection — too many joins too fast triggers a response
    (kick/timeout new joiners, or just alert), auto-clearing when it calms down.
  * New-account gating — optionally bounce accounts younger than a threshold.
  * Phishing-link filter — deletes messages containing blocklisted domains and
    the classic "free nitro" scam shape.
  * Warn ladder — !warn accrues strikes that auto-escalate mute → kick → ban.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import discord
from discord.ext import commands

from ..analysis import URL_RE
from ..ratelimit import SlidingWindow

# Built-in seed of known scam shapes; extend via RAID_LINK_BLOCKLIST file.
_SCAM_DOMAINS = {
    "discord-nitro.com", "discordnitro.gift", "steamcommunity.ru",
    "discrod.gift", "dlscord.gift", "discord-gift.ru", "free-nitro.ru",
}
_NITRO_SCAM = re.compile(r"(free\s+nitro|nitro\s+for\s+free|@everyone.*http)", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"https?://([^/\s]+)", re.IGNORECASE)


def is_mod():
    async def predicate(ctx: commands.Context) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        perms = getattr(ctx.author, "guild_permissions", None)
        return bool(perms and (perms.manage_messages or perms.ban_members))

    return commands.check(predicate)


class Raid(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cfg = bot.cfg.raid
        self.joins = SlidingWindow(self.cfg.join_limit, self.cfg.join_window)
        self._raid_until: dict[int, float] = {}
        self.blocklist = set(_SCAM_DOMAINS)
        if self.cfg.link_blocklist:
            self._load_blocklist(self.cfg.link_blocklist)

    def _load_blocklist(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                d = line.strip().lower()
                if d and not d.startswith("#"):
                    self.blocklist.add(d)

    # -- raid detection ---------------------------------------------------- #
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not self.cfg.enabled:
            return
        guild = member.guild
        # new-account gate
        min_age = self.bot.settings.get_int(
            guild.id, "raid.min_account_age_hours", self.cfg.min_account_age_hours
        )
        if min_age > 0:
            age_h = (discord.utils.utcnow() - member.created_at).total_seconds() / 3600
            if age_h < min_age:
                try:
                    await member.kick(reason=f"account younger than {min_age}h")
                    await self._alert(guild, f"Bounced new account {member} (age {age_h:.1f}h).")
                except discord.HTTPException:
                    pass
                return

        # join-velocity
        count = self.joins.hit(guild.id)
        limit = self.bot.settings.get_int(guild.id, "raid.join_limit", self.cfg.join_limit)
        now = time.time()
        raiding = now < self._raid_until.get(guild.id, 0)
        if count > limit or raiding:
            self._raid_until[guild.id] = now + self.cfg.join_window
            await self._handle_raid_join(member)

    async def _handle_raid_join(self, member: discord.Member) -> None:
        action = self.bot.settings.get_str(member.guild.id, "raid.action", self.cfg.raid_action)
        try:
            if action == "kick":
                await member.kick(reason="raid protection")
            elif action == "lockdown":
                until = discord.utils.utcnow() + __import__("datetime").timedelta(
                    seconds=self.cfg.mute_seconds
                )
                await member.timeout(until, reason="raid protection (lockdown)")
        except discord.HTTPException:
            pass
        await self._alert(member.guild, f"🚨 Raid response ({action}) applied to {member}.")

    async def _alert(self, guild: discord.Guild, text: str) -> None:
        await self.bot.log_mod_event(
            guild_id=guild.id, user_id=None, channel_id=None,
            kind="raid", action="alert", reason=text, severity=0.7,
        )

    # -- phishing / scam links --------------------------------------------- #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self.cfg.enabled or message.author.bot or message.guild is None:
            return
        perms = getattr(message.author, "guild_permissions", None)
        if perms and (perms.manage_messages or perms.administrator):
            return
        if self.bot.settings.get_bool(message.guild.id, "enforce.paused", False):
            return
        content = message.content or ""
        if not URL_RE.search(content) and not _NITRO_SCAM.search(content):
            return
        hit = None
        for domain in _DOMAIN_RE.findall(content):
            base = domain.lower().lstrip("www.")
            if any(base == d or base.endswith("." + d) for d in self.blocklist):
                hit = base
                break
        if hit is None and _NITRO_SCAM.search(content):
            hit = "nitro-scam-pattern"
        if hit is None:
            return
        mod = self.bot.get_cog("Moderation")
        if mod is not None:
            await mod.enforce(  # type: ignore[attr-defined]
                message, kind="scam", action="delete",
                reason=f"phishing/scam: {hit}", severity=0.85,
            )

    # -- warn ladder ------------------------------------------------------- #
    @commands.command(name="warn")
    @commands.guild_only()
    @is_mod()
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "—") -> None:
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, member.id, ctx.author.id, reason, time.time()),
        )
        row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS c FROM warnings WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, member.id),
        )
        count = row["c"] if row else 1
        await ctx.send(f"⚠️ Warned {member.mention}. Total warnings: **{count}**. Reason: {reason}")
        await self._escalate(ctx, member, count)

    async def _escalate(self, ctx, member: discord.Member, count: int) -> None:
        g = ctx.guild.id
        to_ban = self.bot.settings.get_int(g, "raid.warn_to_ban", self.cfg.warn_to_ban)
        to_kick = self.bot.settings.get_int(g, "raid.warn_to_kick", self.cfg.warn_to_kick)
        to_mute = self.bot.settings.get_int(g, "raid.warn_to_mute", self.cfg.warn_to_mute)
        try:
            if count >= to_ban:
                await ctx.guild.ban(member, reason=f"{count} warnings")
                await ctx.send(f"🔨 {member} auto-banned at {count} warnings.")
            elif count >= to_kick:
                await member.kick(reason=f"{count} warnings")
                await ctx.send(f"👢 {member} auto-kicked at {count} warnings.")
            elif count >= to_mute:
                until = discord.utils.utcnow() + __import__("datetime").timedelta(
                    seconds=self.cfg.mute_seconds
                )
                await member.timeout(until, reason=f"{count} warnings")
                await ctx.send(f"⏳ {member} auto-muted at {count} warnings.")
        except discord.Forbidden:
            await ctx.send("(Couldn't apply escalation — check my role position/permissions.)")

    @commands.command(name="warnings")
    @commands.guild_only()
    @is_mod()
    async def warnings(self, ctx: commands.Context, member: discord.Member) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT reason, ts FROM warnings WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 15",
            (ctx.guild.id, member.id),
        )
        if not rows:
            await ctx.send(f"{member} has no warnings.")
            return
        lines = [f"<t:{int(r['ts'])}:d> — {r['reason']}" for r in rows]
        await ctx.send(f"**Warnings for {member}:**\n" + "\n".join(lines))

    @commands.command(name="clearwarns")
    @commands.guild_only()
    @is_mod()
    async def clearwarns(self, ctx: commands.Context, member: discord.Member) -> None:
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)
        )
        await ctx.send(f"🧽 Cleared warnings for {member}.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Raid(bot))
