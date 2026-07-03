"""Live health dashboard + a quick in-process benchmark.

``health`` renders the same snapshot the /metrics endpoint and Zabbix see, so
you can eyeball the Pi from Discord. ``bench`` times how many messages/sec the
deterministic analyzer can chew through on *this* hardware — a safe taste of
the load the full stress harness (scripts/stress.py) applies.
"""

from __future__ import annotations

import time

import discord
from discord.ext import commands


def _bar(pct: float, width: int = 12) -> str:
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


class Health(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="health", aliases=["status", "stats"])
    async def health(self, ctx: commands.Context) -> None:
        s = self.bot.metrics.snapshot()
        temp = s["cpu_temp_c"]
        temp_str = f"{temp:.1f}°C" if temp is not None else "n/a"
        # warn colors as the Pi heats up / falls behind
        color = discord.Color.green()
        if (temp and temp >= 75) or s["loop_lag_ms"] > 250 or s["mem_used_pct"] > 90:
            color = discord.Color.orange()
        if (temp and temp >= 82) or s["loop_lag_ms"] > 1000 or s["llm_breaker_open"]:
            color = discord.Color.red()

        embed = discord.Embed(title="🍓 Pi health", color=color)
        embed.add_field(name="Uptime", value=f"{s['uptime_s']/3600:.1f} h", inline=True)
        embed.add_field(name="Guilds", value=str(s["guilds"]), inline=True)
        embed.add_field(name="Gateway", value=f"{s['latency_ms']} ms", inline=True)
        embed.add_field(name="CPU temp", value=temp_str, inline=True)
        embed.add_field(
            name="Loop lag", value=f"{s['loop_lag_ms']} ms (max {s['loop_lag_max_ms']})", inline=True
        )
        embed.add_field(name="Load1", value=str(s["load1"]), inline=True)
        embed.add_field(
            name="Memory", value=f"{_bar(s['mem_used_pct'])} {s['mem_used_pct']}%", inline=False
        )
        embed.add_field(
            name="Moderation",
            value=f"seen {s['messages_seen']} · actions {s['mod_actions']} · "
            f"spam {s['spam_trips']} · escalations {s['escalations']}",
            inline=False,
        )
        embed.add_field(
            name="LLM router",
            value=f"calls {s['llm_calls']} · cache {s['llm_cache_hits']} · "
            f"fail {s['llm_failures']} · {s['llm_avg_latency_ms']}ms · "
            f"breaker {'OPEN' if s['llm_breaker_open'] else 'ok'}",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="bench")
    @commands.is_owner()
    async def bench(self, ctx: commands.Context, seconds: int = 2) -> None:
        """Benchmark analyzer throughput on this hardware (msgs/sec)."""
        seconds = max(1, min(10, seconds))
        samples = [
            "hey everyone how's it going today",
            "CHECK OUT THIS FREE NITRO http://scam.example @everyone",
            "f u c k this stupid thing",
            "🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉",
            "anyone know how to configure the search operators?",
        ]
        msg = await ctx.send(f"⏱️ Benchmarking analyzer for {seconds}s…")
        count = 0
        end = time.monotonic() + seconds
        i = 0
        while time.monotonic() < end:
            for _ in range(200):  # batch so we don't call monotonic() too often
                self.bot.analyzer.analyze(samples[i % len(samples)])
                i += 1
                count += 1
        rate = count / seconds
        await msg.edit(
            content=f"⚡ **{rate:,.0f} msgs/sec** analyzed "
            f"({count:,} messages in {seconds}s). "
            f"Loop lag now: {round(self.bot.metrics.lag.last_lag_ms)}ms."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Health(bot))
