"""User ranking: XP, levels, reputation, badges, level-roles, weekly digest.

XP is awarded per message (with an anti-farm cooldown) and per reaction
received. Levels come from a simple power curve. Optionally the bot assigns a
role when a member crosses a level (configure via
``!set rank.role.<level> <role_id>``). All state lives in SQLite so it survives
restarts and is cheap on a Pi.
"""

from __future__ import annotations

import math
import time

import discord
from discord.ext import commands, tasks

BADGE_MILESTONES = {
    100: "💬 Chatterbox",
    1000: "🗣️ Regular",
    5000: "🎖️ Veteran",
    25000: "👑 Legend",
}


def level_for_xp(xp: int, base: int, exponent: float) -> int:
    """Largest n with base * n**exponent <= xp."""
    n = 0
    while base * ((n + 1) ** exponent) <= xp:
        n += 1
        if n > 1000:  # safety
            break
    return n


def xp_for_level(level: int, base: int, exponent: float) -> int:
    # ceil so this is the exact XP that first *reaches* the level (round-trips
    # with level_for_xp instead of landing one short from truncation).
    return int(math.ceil(base * (level**exponent)))


class Ranking(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cfg = bot.cfg.ranking
        if self.cfg.enabled:
            self.weekly_digest.start()

    def cog_unload(self) -> None:
        self.weekly_digest.cancel()

    # -- xp on activity ---------------------------------------------------- #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self.cfg.enabled or message.author.bot or message.guild is None:
            return
        gid, uid = message.guild.id, message.author.id
        row = await self.bot.db.fetchone(
            "SELECT xp, last_xp_ts FROM users WHERE guild_id=? AND user_id=?", (gid, uid)
        )
        now = time.time()
        await self.bot.db.execute(
            "INSERT INTO users (guild_id, user_id, messages) VALUES (?, ?, 1) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET messages = messages + 1",
            (gid, uid),
        )
        last = row["last_xp_ts"] if row else 0
        if now - last < self.cfg.xp_cooldown_seconds:
            return
        old_xp = row["xp"] if row else 0
        new_xp = old_xp + self.cfg.xp_per_message
        await self.bot.db.execute(
            "UPDATE users SET xp=?, last_xp_ts=? WHERE guild_id=? AND user_id=?",
            (new_xp, now, gid, uid),
        )
        await self._check_levelup(message, old_xp, new_xp)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        if not self.cfg.enabled or user.bot:
            return
        msg = reaction.message
        if msg.guild is None or msg.author.bot or msg.author.id == user.id:
            return
        await self.bot.db.execute(
            "INSERT INTO users (guild_id, user_id, xp) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = xp + ?",
            (msg.guild.id, msg.author.id, self.cfg.xp_per_reaction, self.cfg.xp_per_reaction),
        )

    async def _check_levelup(self, message, old_xp: int, new_xp: int) -> None:
        base, exp = self.cfg.level_base, self.cfg.level_exponent
        old_lvl = level_for_xp(old_xp, base, exp)
        new_lvl = level_for_xp(new_xp, base, exp)
        if new_lvl > old_lvl and new_lvl > 0:
            await self._assign_level_role(message.author, new_lvl, message.guild)
            if self.bot.settings.get_bool(message.guild.id, "rank.announce", True):
                try:
                    await message.channel.send(
                        f"🎉 {message.author.mention} reached **level {new_lvl}**!"
                    )
                except discord.HTTPException:
                    pass
        # badges
        for threshold, badge in BADGE_MILESTONES.items():
            if old_xp < threshold <= new_xp:
                await self.bot.db.execute(
                    "INSERT OR IGNORE INTO user_badges (guild_id, user_id, badge, ts) "
                    "VALUES (?, ?, ?, ?)",
                    (message.guild.id, message.author.id, badge, time.time()),
                )

    async def _assign_level_role(self, member, level: int, guild) -> None:
        role_id = self.bot.settings.get_int(guild.id, f"rank.role.{level}", 0)
        if not role_id:
            return
        role = guild.get_role(role_id)
        if role is not None and isinstance(member, discord.Member):
            try:
                await member.add_roles(role, reason=f"reached level {level}")
            except discord.HTTPException:
                pass

    # -- commands ---------------------------------------------------------- #
    @commands.command(name="rank", aliases=["level", "xp"])
    async def rank(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        member = member or ctx.author
        row = await self.bot.db.fetchone(
            "SELECT xp, messages, rep FROM users WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, member.id),
        )
        xp = row["xp"] if row else 0
        base, exp = self.cfg.level_base, self.cfg.level_exponent
        lvl = level_for_xp(xp, base, exp)
        nxt = xp_for_level(lvl + 1, base, exp)
        badges = await self.bot.db.fetchall(
            "SELECT badge FROM user_badges WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, member.id),
        )
        embed = discord.Embed(title=f"{member.display_name}", color=discord.Color.blurple())
        embed.add_field(name="Level", value=str(lvl), inline=True)
        embed.add_field(name="XP", value=f"{xp} / {nxt}", inline=True)
        embed.add_field(name="Rep", value=str(row["rep"] if row else 0), inline=True)
        embed.add_field(name="Messages", value=str(row["messages"] if row else 0), inline=True)
        if badges:
            embed.add_field(
                name="Badges", value=" ".join(b["badge"] for b in badges), inline=False
            )
        await ctx.send(embed=embed)

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    async def leaderboard(self, ctx: commands.Context) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT user_id, xp FROM users WHERE guild_id=? ORDER BY xp DESC LIMIT 10",
            (ctx.guild.id,),
        )
        if not rows:
            await ctx.send("No ranked users yet.")
            return
        base, exp = self.cfg.level_base, self.cfg.level_exponent
        lines = []
        for i, row in enumerate(rows, 1):
            lvl = level_for_xp(row["xp"], base, exp)
            lines.append(f"**{i}.** <@{row['user_id']}> — L{lvl} ({row['xp']} xp)")
        embed = discord.Embed(
            title="🏆 Leaderboard", description="\n".join(lines), color=discord.Color.gold()
        )
        await ctx.send(embed=embed)

    @commands.command(name="rep")
    @commands.guild_only()
    async def rep(self, ctx: commands.Context, member: discord.Member) -> None:
        """Give a reputation point to someone (rate-limited per pair)."""
        if member.id == ctx.author.id:
            await ctx.send("You can't rep yourself. 🙂")
            return
        if member.bot:
            await ctx.send("Bots don't need rep.")
            return
        now = time.time()
        last = await self.bot.db.fetchone(
            "SELECT ts FROM rep_log WHERE guild_id=? AND giver_id=? AND target_id=?",
            (ctx.guild.id, ctx.author.id, member.id),
        )
        if last and now - last["ts"] < self.cfg.rep_cooldown_seconds:
            remaining = int(self.cfg.rep_cooldown_seconds - (now - last["ts"]))
            await ctx.send(f"You repped them recently. Try again in {remaining // 60} min.")
            return
        await self.bot.db.execute(
            "INSERT INTO rep_log (guild_id, giver_id, target_id, ts) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, giver_id, target_id) DO UPDATE SET ts=excluded.ts",
            (ctx.guild.id, ctx.author.id, member.id, now),
        )
        await self.bot.db.execute(
            "INSERT INTO users (guild_id, user_id, rep) VALUES (?, ?, 1) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET rep = rep + 1",
            (ctx.guild.id, member.id),
        )
        await ctx.send(f"👍 {ctx.author.display_name} repped {member.display_name}!")

    # -- weekly digest ----------------------------------------------------- #
    @tasks.loop(hours=168)
    async def weekly_digest(self) -> None:
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            channel_id = self.bot.settings.get_int(guild.id, "rank.digest_channel", 0)
            if not channel_id:
                continue
            channel = guild.get_channel(channel_id)
            if channel is None:
                continue
            rows = await self.bot.db.fetchall(
                "SELECT user_id, xp FROM users WHERE guild_id=? ORDER BY xp DESC LIMIT 5",
                (guild.id,),
            )
            if not rows:
                continue
            lines = [f"<@{r['user_id']}> — {r['xp']} xp" for r in rows]
            embed = discord.Embed(
                title="📊 Weekly top chatters",
                description="\n".join(lines),
                color=discord.Color.green(),
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Ranking(bot))
