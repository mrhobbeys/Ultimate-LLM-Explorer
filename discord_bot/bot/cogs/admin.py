"""Admin: onboarding wizard, live settings, backups.

Everything the install-time wizard can set is *also* settable at runtime with
``set``/``get`` — that's the "skip setup, configure via commands" model. The
``setup`` command re-runs the guided flow any time.
"""

from __future__ import annotations

import asyncio
import os
import time

import discord
from discord.ext import commands

from ..presets import ORDER, PRESETS, resolve, summary_line

# keys the wizard touches, with a hint shown to the user
KNOWN_KEYS = {
    "mod.mode": "off | shadow | approve | armed",
    "mod.suspicion_low": "0-1 lower escalation threshold",
    "mod.suspicion_high": "0-1 act-directly threshold",
    "mod.profanity_action": "delete | warn | timeout | log",
    "mod.llm_escalation": "true | false",
    "spam.action": "delete | timeout | warn | log",
    "spam.max_messages": "int, messages per window",
    "spam.max_mentions": "int",
    "spam.max_links": "int",
    "log.channel": "channel id for the mod/activity log",
    "log.messages": "true | false — log every message (heavy!)",
    "admin.role": "role id that grants DM admin control",
    "rank.announce": "true | false — announce level-ups",
    "rank.digest_channel": "channel id for the weekly digest",
    "raid.min_account_age_hours": "int, 0 = off",
    "raid.action": "lockdown | kick | log",
}


def is_admin():
    async def predicate(ctx: commands.Context) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        perms = getattr(ctx.author, "guild_permissions", None)
        return bool(perms and (perms.administrator or perms.manage_guild))

    return commands.check(predicate)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -- live settings ----------------------------------------------------- #
    @commands.command(name="set")
    @commands.guild_only()
    @is_admin()
    async def set_cmd(self, ctx: commands.Context, key: str, *, value: str) -> None:
        # sugar: accept #channel / @role and store their ids
        if ctx.message.channel_mentions and value.strip().startswith("<#"):
            value = str(ctx.message.channel_mentions[0].id)
        if ctx.message.role_mentions and value.strip().startswith("<@&"):
            value = str(ctx.message.role_mentions[0].id)
        await self.bot.settings.set(ctx.guild.id, key, value)
        hint = KNOWN_KEYS.get(key, "")
        await ctx.send(f"✅ `{key}` = `{value}`" + (f"  _( {hint} )_" if hint else ""))

    @commands.command(name="get", aliases=["settings"])
    @commands.guild_only()
    @is_admin()
    async def get_cmd(self, ctx: commands.Context, key: str = "") -> None:
        overrides = self.bot.settings.all_for(ctx.guild.id)
        if key:
            await ctx.send(f"`{key}` = `{overrides.get(key, '(default)')}`")
            return
        if not overrides:
            await ctx.send("No per-server overrides set. Run `setup` or `set <key> <value>`.")
            return
        lines = [f"`{k}` = `{v}`" for k, v in sorted(overrides.items())]
        await ctx.send("**Server settings:**\n" + "\n".join(lines[:40]))

    @commands.command(name="keys")
    @is_admin()
    async def keys(self, ctx: commands.Context) -> None:
        lines = [f"`{k}` — {hint}" for k, hint in KNOWN_KEYS.items()]
        await ctx.send("**Settable keys:**\n" + "\n".join(lines))

    # -- personality presets ----------------------------------------------- #
    async def apply_preset(self, guild_id: int, key: str) -> None:
        preset = PRESETS[key]
        for k, v in preset.settings().items():
            await self.bot.settings.set(guild_id, k, v)

    @commands.command(name="preset", aliases=["presets", "vibe"])
    @commands.guild_only()
    @is_admin()
    async def preset_cmd(self, ctx: commands.Context, *, name: str = "") -> None:
        """Set the server's vibe in one shot, or list the options."""
        if not name:
            current = self.bot.settings.get_str(ctx.guild.id, "server.preset", "(none)")
            lines = [summary_line(PRESETS[k]) for k in ORDER]
            embed = discord.Embed(
                title="🎚️ Server personality presets",
                description="\n\n".join(lines),
                color=discord.Color.blurple(),
            )
            embed.set_footer(text=f"Current: {current} · apply with {ctx.prefix}preset <name>")
            await ctx.send(embed=embed)
            return
        preset = resolve(name)
        if preset is None:
            await ctx.send(f"Unknown preset. Options: {', '.join(f'`{k}`' for k in ORDER)}")
            return
        await self.apply_preset(ctx.guild.id, preset.key)
        await ctx.send(
            f"{preset.emoji} Applied **{preset.name}**. {preset.blurb}\n"
            f"Fine-tune anything with `{ctx.prefix}set` or `{ctx.prefix}mod sensitivity`."
        )

    # -- onboarding wizard ------------------------------------------------- #
    @commands.command(name="setup")
    @commands.guild_only()
    @is_admin()
    async def setup_cmd(self, ctx: commands.Context) -> None:
        """Guided onboarding. Answer or type `skip`; `cancel` to abort."""
        await ctx.send(
            "🛠️ **Setup wizard.** First, what kind of server is this? That sets "
            "your whole moderation vibe in one shot. Reply `skip` to keep "
            "current settings, or `cancel` to stop."
        )

        def check(m: discord.Message) -> bool:
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        async def ask(prompt: str) -> str | None:
            await ctx.send(prompt)
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=120)
            except asyncio.TimeoutError:
                await ctx.send("⏰ Timed out. Run `setup` again when ready.")
                return None
            content = msg.content.strip()
            if content.lower() == "cancel":
                await ctx.send("Cancelled.")
                return None
            return content

        # step 0: personality preset
        preset_list = "\n".join(summary_line(PRESETS[k]) for k in ORDER)
        ans = await ask(f"🎚️ **Pick your server's vibe:**\n\n{preset_list}\n\n"
                        "Type a preset name (e.g. `gamer`, `family`, `fellowship`) or `skip`.")
        if ans is None:
            return
        if ans.lower() != "skip":
            preset = resolve(ans)
            if preset is not None:
                await self.apply_preset(ctx.guild.id, preset.key)
                await ctx.send(f"{preset.emoji} Applied **{preset.name}**. Now a few details…")
            else:
                await ctx.send("Didn't recognize that preset — leaving moderation as-is.")

        steps = [
            ("log.channel",
             "1️⃣ Mention the channel for logs (e.g. #mod-log), or `skip`."),
            ("admin.role",
             "2️⃣ Mention the role that may DM-control the bot, or `skip`."),
            ("rank.announce",
             "3️⃣ Announce level-ups in chat? `true` / `false`"),
        ]
        for key, prompt in steps:
            ans = await ask(prompt)
            if ans is None:
                return
            if ans.lower() == "skip":
                continue
            # resolve mentions to ids
            if key == "log.channel" and ctx.message and ans.startswith("<#"):
                ans = ans.strip("<#>")
            await self.bot.settings.set(ctx.guild.id, key, ans.strip("<#@&>"))
        await ctx.send("🎉 Setup complete! Use `get` to review, `set` to tweak anything.")

    # -- panic killswitch -------------------------------------------------- #
    @commands.command(name="panic")
    @commands.guild_only()
    @is_admin()
    async def panic(self, ctx: commands.Context, state: str = "on") -> None:
        """Instantly pause ALL automated enforcement (spam/mod/raid) here.

        `panic on` freezes the bot's hands; `panic off` resumes. Manual DM/mod
        commands still work — this only stops automatic actions.
        """
        paused = state.lower() not in {"off", "false", "0", "resume"}
        await self.bot.settings.set(ctx.guild.id, "enforce.paused", "true" if paused else "false")
        if paused:
            await ctx.send("🛑 **Enforcement paused.** No automatic actions until `panic off`.")
        else:
            await ctx.send("▶️ **Enforcement resumed.**")

    # -- backup ------------------------------------------------------------ #
    @commands.command(name="backup")
    @commands.is_owner()
    async def backup(self, ctx: commands.Context) -> None:
        ts = time.strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(self.bot.cfg.backup_dir or "data/backups", f"bot-{ts}.db")
        await ctx.send("💾 Backing up…")
        try:
            path = await self.bot.db.backup(dest)
        except Exception as exc:  # noqa: BLE001
            await ctx.send(f"❌ Backup failed: {exc}")
            return
        size = os.path.getsize(path) / 1024
        await ctx.send(f"✅ Backed up to `{path}` ({size:.0f} KiB).")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
