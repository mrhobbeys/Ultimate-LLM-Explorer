"""Moderation: deterministic checks first, LLM only for the uncertain middle,
enforcement centralized behind a mode switch (off/shadow/approve/armed).

Pipeline for every message:
  1. Cheap deterministic profanity check (leet-normalized).  -> act
  2. Compute a suspicion score from message shape.
  3. suspicion < low   -> ignore (the common case; free)
     suspicion >= high -> act deterministically
     in between        -> ask the offboard LLM, act on its verdict
The LLM's text NEVER goes to chat — it only produces a delete/timeout/ban.

Enforcement respects the guild's mode:
  * off     — nothing
  * shadow  — log what it *would* do
  * approve — DM the owner "ban so-and-so? yes/no" for destructive actions
              (kick/ban); delete/timeout happen immediately
  * armed   — everything happens automatically

DM approvals are persisted, so a reboot doesn't drop a pending decision.
"""

from __future__ import annotations

import time

import discord
from discord.ext import commands

DESTRUCTIVE = {"kick", "ban"}


def is_mod():
    async def predicate(ctx: commands.Context) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        perms = getattr(ctx.author, "guild_permissions", None)
        return bool(perms and (perms.manage_messages or perms.ban_members))

    return commands.check(predicate)


class ApprovalView(discord.ui.View):
    """Persistent Yes/No buttons on the approval DM.

    custom_ids are static so the view re-registers after a restart; we look the
    pending action up by the DM message id the buttons live on.
    """

    def __init__(self, cog: "Moderation | None" = None) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.danger, custom_id="mod:approve")
    async def approve(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await self._resolve(interaction, approved=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.secondary, custom_id="mod:deny")
    async def deny(self, interaction: discord.Interaction, _b: discord.ui.Button) -> None:
        await self._resolve(interaction, approved=False)

    async def _resolve(self, interaction: discord.Interaction, approved: bool) -> None:
        cog: Moderation = self.cog or interaction.client.get_cog("Moderation")  # type: ignore
        if cog is None:
            return
        await cog.resolve_pending(interaction, approved)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cfg = bot.cfg.moderation

    async def cog_load(self) -> None:
        # register the persistent view so buttons survive restarts
        self.bot.add_view(ApprovalView(self))

    # -- effective per-guild settings -------------------------------------- #
    def mode(self, gid: int | None) -> str:
        return self.bot.settings.get_str(gid, "mod.mode", self.cfg.mode)

    def slow(self, gid: int | None) -> float:
        return self.bot.settings.get_float(gid, "mod.suspicion_low", self.cfg.suspicion_low)

    def shigh(self, gid: int | None) -> float:
        return self.bot.settings.get_float(gid, "mod.suspicion_high", self.cfg.suspicion_high)

    # -- main listener ----------------------------------------------------- #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self.cfg.enabled:
            return
        if message.author.bot or message.guild is None:
            return
        if not message.content:
            return
        gid = message.guild.id
        if self.mode(gid) == "off" or self.bot.settings.get_bool(gid, "enforce.paused", False):
            return
        # never moderate staff
        perms = getattr(message.author, "guild_permissions", None)
        if perms and (perms.manage_messages or perms.administrator):
            return

        self.bot.metrics.messages_seen += 1
        shape = self.bot.analyzer.analyze(message.content)

        # 1. deterministic profanity
        if shape.has_profanity:
            await self.enforce(
                message,
                kind="profanity",
                action=self.bot.settings.get_str(gid, "mod.profanity_action", self.cfg.profanity_action),
                reason=f"profanity: {', '.join(shape.profanity_hits[:3])}",
                severity=0.6,
            )
            return

        # 2/3. suspicion routing
        low, high = self.slow(gid), self.shigh(gid)
        if shape.suspicion >= high:
            await self.enforce(
                message, kind="heuristic", action="delete",
                reason=f"high suspicion {shape.suspicion:.2f}", severity=shape.suspicion,
            )
            return
        if (
            shape.suspicion >= low
            and self.cfg.llm_escalation_enabled
            and self.bot.settings.get_bool(gid, "mod.llm_escalation", self.cfg.llm_escalation_enabled)
            and len(message.content) >= self.cfg.min_escalation_len
        ):
            await self._escalate(message, shape)

    async def _escalate(self, message: discord.Message, shape) -> None:
        self.bot.metrics.escalations += 1
        verdict = await self.bot.llm.classify(message.content)
        if not verdict.ok or not verdict.is_harmful:
            return
        sev = verdict.severity
        if sev >= self.cfg.llm_ban_severity:
            action = "ban"
        elif sev >= self.cfg.llm_timeout_severity:
            action = "timeout"
        elif sev >= self.cfg.llm_delete_severity:
            action = "delete"
        else:
            return
        await self.enforce(
            message, kind="llm", action=action,
            reason=f"{verdict.category}: {verdict.reason}", severity=sev,
        )

    # -- enforcement ------------------------------------------------------- #
    async def enforce(
        self,
        message: discord.Message | None,
        *,
        kind: str,
        action: str,
        reason: str,
        severity: float,
        guild: discord.Guild | None = None,
        member: discord.Member | None = None,
    ) -> None:
        guild = guild or (message.guild if message else None)
        member = member or (message.author if message else None)  # type: ignore
        if guild is None:
            return
        gid = guild.id
        mode = self.mode(gid)
        self.bot.metrics.mod_actions += 1

        if mode == "shadow":
            await self._record(guild, member, message, kind, "shadow", reason, severity)
            return

        destructive = action in DESTRUCTIVE
        if mode == "approve" and destructive:
            await self._request_approval(guild, member, message, action, reason, severity)
            return

        # armed, or approve-mode non-destructive: act now
        await self._apply(guild, member, message, action, reason, severity, kind)

    async def _apply(self, guild, member, message, action, reason, severity, kind) -> None:
        ok = True
        try:
            if action == "delete" and message is not None:
                await message.delete()
            elif action == "timeout" and isinstance(member, discord.Member):
                secs = self.cfg.llm_timeout_seconds
                await member.timeout(discord.utils.utcnow() + _td(secs), reason=reason)
            elif action == "kick" and isinstance(member, discord.Member):
                await member.kick(reason=reason)
            elif action == "ban" and isinstance(member, discord.Member):
                await guild.ban(member, reason=reason, delete_message_seconds=0)
        except (discord.Forbidden, discord.HTTPException):
            ok = False
        await self._record(
            guild, member, message, kind, action if ok else f"{action}:failed", reason, severity
        )
        if isinstance(member, discord.Member):
            await self.bot.db.execute(
                "UPDATE users SET infractions = infractions + 1 "
                "WHERE guild_id=? AND user_id=?",
                (guild.id, member.id),
            )

    async def _record(self, guild, member, message, kind, action, reason, severity) -> None:
        await self.bot.log_mod_event(
            guild_id=guild.id if guild else None,
            user_id=member.id if member else None,
            channel_id=message.channel.id if message else None,
            kind=kind,
            action=action,
            reason=reason,
            severity=severity,
        )

    # -- approval workflow ------------------------------------------------- #
    def _owner_targets(self) -> list[int]:
        ids = list(self.bot.owner_ids or [])
        if not ids and self.bot.owner_id:
            ids = [self.bot.owner_id]
        return ids

    async def _request_approval(self, guild, member, message, action, reason, severity) -> None:
        targets = self._owner_targets()
        if not targets:
            # no one to ask — fall back to shadow-log so nothing silently bans
            await self._record(guild, member, message, "approval", "no_owner", reason, severity)
            return
        embed = discord.Embed(
            title=f"Approve {action}?",
            description=reason,
            color=discord.Color.red(),
        )
        if member:
            embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Guild", value=str(guild), inline=True)
        embed.add_field(name="Severity", value=f"{severity:.2f}", inline=True)
        embed.set_footer(text=f"React Approve to {action}. Expires soon.")

        for uid in targets:
            user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
            if user is None:
                continue
            try:
                dm = await user.send(embed=embed, view=ApprovalView(self))
            except (discord.Forbidden, discord.HTTPException):
                continue
            await self.bot.db.execute(
                "INSERT INTO pending_actions "
                "(guild_id, target_id, channel_id, src_message, dm_message, action, "
                " reason, severity, status, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    guild.id,
                    member.id if member else None,
                    message.channel.id if message else None,
                    message.id if message else None,
                    dm.id,
                    action,
                    reason,
                    severity,
                    time.time(),
                ),
            )
            return  # ask the first reachable owner only

    async def resolve_pending(self, interaction: discord.Interaction, approved: bool) -> None:
        row = await self.bot.db.fetchone(
            "SELECT * FROM pending_actions WHERE dm_message=?", (interaction.message.id,)
        )
        if row is None or row["status"] != "pending":
            await interaction.response.send_message("Already handled.", ephemeral=True)
            return
        new_status = "approved" if approved else "denied"
        await self.bot.db.execute(
            "UPDATE pending_actions SET status=? WHERE id=?", (new_status, row["id"])
        )
        guild = self.bot.get_guild(row["guild_id"])
        if approved and guild is not None:
            member = guild.get_member(row["target_id"]) if row["target_id"] else None
            message = None  # source message may be gone; delete is best-effort
            await self._apply(
                guild, member, message, row["action"], row["reason"], row["severity"], "approved"
            )
            verdict_text = f"✅ {row['action']} executed."
        else:
            verdict_text = "🚫 Denied — no action taken." if not approved else "Guild unavailable."
        try:
            await interaction.response.edit_message(content=verdict_text, view=None)
        except discord.HTTPException:
            pass

    # -- commands ---------------------------------------------------------- #
    @commands.group(name="mod", invoke_without_command=True)
    @is_mod()
    async def mod(self, ctx: commands.Context) -> None:
        gid = ctx.guild.id if ctx.guild else None
        await ctx.send(
            f"**Moderation** · mode=`{self.mode(gid)}` "
            f"suspicion=[{self.slow(gid):.2f}, {self.shigh(gid):.2f}]\n"
            f"Use `{ctx.prefix}mod mode <off|shadow|approve|armed>` or "
            f"`{ctx.prefix}mod sensitivity <0-1>`."
        )

    @mod.command(name="mode")
    @is_mod()
    async def mod_mode(self, ctx: commands.Context, mode: str) -> None:
        mode = mode.lower()
        if mode not in {"off", "shadow", "approve", "armed"}:
            await ctx.send("Mode must be one of: off, shadow, approve, armed.")
            return
        await self.bot.settings.set(ctx.guild.id, "mod.mode", mode)
        await ctx.send(f"Moderation mode set to **{mode}**.")

    @mod.command(name="sensitivity")
    @is_mod()
    async def mod_sensitivity(self, ctx: commands.Context, level: float) -> None:
        """Crank moderation up (1.0 = twitchy) or down (0.0 = relaxed).

        This maps a single dial onto the two suspicion thresholds so you don't
        have to reason about both.
        """
        level = max(0.0, min(1.0, level))
        # higher sensitivity -> lower thresholds
        low = round(0.4 * (1 - level) + 0.05, 3)
        high = round(0.9 * (1 - level) + 0.3, 3)
        await self.bot.settings.set(ctx.guild.id, "mod.suspicion_low", low)
        await self.bot.settings.set(ctx.guild.id, "mod.suspicion_high", high)
        await ctx.send(f"Sensitivity **{level:.2f}** → thresholds low={low}, high={high}.")

    @mod.command(name="test")
    @is_mod()
    async def mod_test(self, ctx: commands.Context, *, text: str) -> None:
        """Dry-run the analyzer on some text and show the shape + suspicion."""
        s = self.bot.analyzer.analyze(text)
        await ctx.send(
            f"suspicion=`{s.suspicion:.2f}` caps=`{s.caps_ratio:.2f}` "
            f"entropy=`{s.entropy:.2f}` profanity=`{s.profanity_hits or '—'}` "
            f"sentiment=`{s.sentiment}`"
        )


def _td(seconds: int):
    import datetime

    return datetime.timedelta(seconds=seconds)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
