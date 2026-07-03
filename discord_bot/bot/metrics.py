"""Telemetry: an event-loop lag sampler, a metrics snapshot, and a tiny HTTP
server exposing ``/healthz``, ``/metrics`` (Prometheus text) and ``/status``
(JSON). A companion status file is written to disk so a Zabbix UserParameter
can read it without an HTTP round-trip.

aiohttp ships with discord.py, so this adds no dependency. On a Pi 1 the whole
thing is a couple of KB of RAM and one lightweight background task.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from aiohttp import web


def read_cpu_temp() -> float | None:
    """Pi CPU temperature in °C, or None if unavailable."""
    path = "/sys/class/thermal/thermal_zone0/temp"
    try:
        return int(Path(path).read_text().strip()) / 1000.0
    except Exception:
        return None


def read_mem() -> dict[str, int]:
    """Total/available memory in KiB from /proc/meminfo (Linux only)."""
    out: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith(("MemTotal", "MemAvailable")):
                key, val = line.split(":", 1)
                out[key.strip()] = int(val.strip().split()[0])
    except Exception:
        pass
    return out


def read_loadavg() -> tuple[float, float, float] | None:
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return None


class LoopLagSampler:
    """Measures asyncio event-loop scheduling lag.

    We schedule a wakeup every ``interval`` seconds and record how late it
    actually fires. On a healthy loop that's ~0 ms; under CPU pressure (the
    exact thing we want to catch on a Pi) it climbs — the single best early
    warning that the bot is falling behind.
    """

    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self.last_lag_ms = 0.0
        self.max_lag_ms = 0.0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            expected = loop.time() + self.interval
            await asyncio.sleep(self.interval)
            lag = max(0.0, (loop.time() - expected)) * 1000.0
            self.last_lag_ms = lag
            self.max_lag_ms = max(self.max_lag_ms, lag)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None


class Metrics:
    def __init__(self, bot) -> None:
        self.bot = bot
        self.lag = LoopLagSampler()
        self.started = time.time()
        # rolling counters other cogs bump
        self.messages_seen = 0
        self.mod_actions = 0
        self.spam_trips = 0
        self.escalations = 0
        self._runner: web.AppRunner | None = None
        self._status_path = bot.cfg.status_path or os.environ.get(
            "BOT_STATUS_FILE", "data/status.json"
        )
        self._write_task: asyncio.Task | None = None

    # -- snapshot ---------------------------------------------------------- #
    def snapshot(self) -> dict:
        mem = read_mem()
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        used_pct = round(100 * (total - avail) / total, 1) if total else 0.0
        load = read_loadavg()
        llm = self.bot.llm
        return {
            "uptime_s": round(time.time() - self.started, 1),
            "ready": self.bot.is_ready(),
            "guilds": len(self.bot.guilds),
            "latency_ms": round((self.bot.latency or 0) * 1000, 1),
            "loop_lag_ms": round(self.lag.last_lag_ms, 1),
            "loop_lag_max_ms": round(self.lag.max_lag_ms, 1),
            "cpu_temp_c": read_cpu_temp(),
            "mem_used_pct": used_pct,
            "mem_avail_kb": avail,
            "load1": round(load[0], 2) if load else None,
            "messages_seen": self.messages_seen,
            "mod_actions": self.mod_actions,
            "spam_trips": self.spam_trips,
            "escalations": self.escalations,
            "llm_calls": llm.calls,
            "llm_cache_hits": llm.cache_hits,
            "llm_failures": llm.failures,
            "llm_avg_latency_ms": round(llm.avg_latency * 1000, 1),
            "llm_breaker_open": int(llm.breaker_open),
            "bayes_spam_msgs": self.bot.bayes.spam_msgs,
            "bayes_ham_msgs": self.bot.bayes.ham_msgs,
            "bayes_catches": self.bot.bayes.catches,
            "bayes_ready": int(self.bot.bayes.ready),
        }

    def prometheus(self) -> str:
        snap = self.snapshot()
        lines = []
        for key, val in snap.items():
            if val is None:
                continue
            if isinstance(val, bool):
                val = int(val)
            if isinstance(val, (int, float)):
                lines.append(f"bot_{key} {val}")
        return "\n".join(lines) + "\n"

    # -- http -------------------------------------------------------------- #
    async def start_http(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.lag.start()
        self._write_task = asyncio.create_task(self._status_writer())
        if port <= 0:
            return  # HTTP disabled; status file + Zabbix still work
        app = web.Application()
        app.router.add_get("/healthz", self._h_health)
        app.router.add_get("/metrics", self._h_metrics)
        app.router.add_get("/status", self._h_status)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()

    async def _h_health(self, _req: web.Request) -> web.Response:
        healthy = self.bot.is_ready() and self.lag.last_lag_ms < 1000
        return web.json_response(
            {"ok": healthy, "ready": self.bot.is_ready()},
            status=200 if healthy else 503,
        )

    async def _h_metrics(self, _req: web.Request) -> web.Response:
        return web.Response(text=self.prometheus(), content_type="text/plain")

    async def _h_status(self, _req: web.Request) -> web.Response:
        return web.json_response(self.snapshot())

    async def _status_writer(self) -> None:
        path = Path(self._status_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.snapshot()))
                tmp.replace(path)  # atomic
            except Exception:
                pass
            await asyncio.sleep(15)

    async def stop(self) -> None:
        self.lag.stop()
        if self._write_task:
            self._write_task.cancel()
        if self._runner is not None:
            await self._runner.cleanup()
