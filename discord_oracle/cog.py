"""The discord.py cog.

Design goal: make it feel like a real terminal / real machine. Once a player
runs ``!oracle start`` in a channel (or DMs the bot), their plain messages in
that channel are routed straight into the engine — no command prefix, no
ceremony — until they ``!oracle stop``. Shell output comes back in a monospaced
code block with the prompt echoed; GUI screens come back as embeds with a clear
options list.

The cog is import-safe without discord installed elsewhere in the package: it is
the only module that imports discord, and the bot entrypoint imports it lazily.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from .config import config
from .engine import Engine, Response
from .llm import LLM
from .state import Store

MAX_BLOCK = 1900  # keep under Discord's 2000-char message limit


def _player_key(guild_id, user_id) -> str:
    return f"{guild_id if guild_id else 'dm'}:{user_id}"


class OracleCog(commands.Cog):
    """A compromised-server text adventure + Windows shell simulation."""

    def __init__(self, bot: commands.Bot, store: Store | None = None) -> None:
        self.bot = bot
        self.store = store or Store(config.db_path)
        self.engine = Engine(self.store, LLM())
        # (channel_id, user_id) -> player_key, hydrated from the DB on load.
        self.active: dict[tuple[str, str], str] = {}
        for channel_id, user_id in self.store.active_session_keys():
            key = self.store.get_session(channel_id, user_id)
            if key:
                self.active[(channel_id, user_id)] = key

    # ---- rendering -----------------------------------------------------
    async def _send(self, channel: discord.abc.Messageable, resp: Response) -> None:
        if resp.kind == "shell":
            body = ""
            if resp.prompt is not None:
                body += resp.prompt
                if resp.echo:
                    body += " " + resp.echo
                body += "\n"
            if resp.body:
                body += resp.body + "\n"
            body += (resp.prompt or "") if resp.prompt is not None else ""
            for chunk in _chunk(body, MAX_BLOCK):
                await channel.send(f"```{chunk}```")
        elif resp.kind == "scene":
            embed = discord.Embed(
                title=resp.title or "Oracle",
                description=resp.body[:4000],
                color=0x2ECC71,
            )
            if resp.options:
                embed.add_field(
                    name="Options",
                    value="\n".join(resp.options)[:1024],
                    inline=False,
                )
            await channel.send(embed=embed)
        else:  # system
            for chunk in _chunk(resp.body, MAX_BLOCK):
                await channel.send(chunk)

        for toast in resp.toasts:
            await channel.send(toast)

    # ---- command group -------------------------------------------------
    @commands.group(name="oracle", invoke_without_command=True)
    async def oracle(self, ctx: commands.Context) -> None:
        await ctx.send(
            "**Oracle** — a compromised Windows server you investigate.\n"
            "`!oracle start` to begin, `!oracle stop` to pause, `!oracle reset` to "
            "wipe your progress, `!oracle status` for your rank & objectives, "
            "`!oracle whereami` to reprint the current screen."
        )

    @oracle.command(name="start")
    async def start(self, ctx: commands.Context) -> None:
        key = _player_key(ctx.guild.id if ctx.guild else None, ctx.author.id)
        player = self.engine.ensure_player(
            key, str(ctx.guild.id) if ctx.guild else None, str(ctx.author.id)
        )
        ch = str(ctx.channel.id)
        self.active[(ch, str(ctx.author.id))] = key
        self.store.set_session(ch, str(ctx.author.id), key)
        await ctx.send(
            "🔓 Session started. From now on, just type — your messages go straight "
            "to the machine. (`!oracle stop` to pause.)"
        )
        await self._send(ctx.channel, self.engine.opening_scene(player))

    @oracle.command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        ch = str(ctx.channel.id)
        self.active.pop((ch, str(ctx.author.id)), None)
        self.store.clear_session(ch, str(ctx.author.id))
        await ctx.send("⏸️ Session paused. Your world is saved. `!oracle start` to resume.")

    @oracle.command(name="reset")
    async def reset(self, ctx: commands.Context) -> None:
        key = _player_key(ctx.guild.id if ctx.guild else None, ctx.author.id)
        player = self.engine.reset_player(
            key, str(ctx.guild.id) if ctx.guild else None, str(ctx.author.id)
        )
        await ctx.send("♻️ World reset to a fresh compromise.")
        ch = str(ctx.channel.id)
        self.active[(ch, str(ctx.author.id))] = key
        self.store.set_session(ch, str(ctx.author.id), key)
        await self._send(ctx.channel, self.engine.opening_scene(player))

    @oracle.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        key = _player_key(ctx.guild.id if ctx.guild else None, ctx.author.id)
        if self.store.get_player(key) is None:
            await ctx.send("No world yet — `!oracle start` first.")
            return
        resp = await self.engine.handle(key, "status")
        await self._send(ctx.channel, resp)

    @oracle.command(name="whereami")
    async def whereami(self, ctx: commands.Context) -> None:
        key = _player_key(ctx.guild.id if ctx.guild else None, ctx.author.id)
        player = self.store.get_player(key)
        if player is None:
            await ctx.send("No world yet — `!oracle start` first.")
            return
        await self._send(ctx.channel, self.engine.opening_scene(player))

    # ---- the immersive message router ---------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # Don't hijack our own command invocations.
        if message.content.startswith(config.command_prefix):
            return
        key = self.active.get((str(message.channel.id), str(message.author.id)))
        if key is None:
            return
        content = message.content.strip()
        if not content:
            return
        async with message.channel.typing():
            resp = await self.engine.handle(key, content)
        await self._send(message.channel, resp)


def _chunk(text: str, size: int) -> list[str]:
    if not text:
        return [""]
    out = []
    while text:
        out.append(text[:size])
        text = text[size:]
    return out


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OracleCog(bot))
