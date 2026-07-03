"""Optional read-only web dashboard.

Deliberately OFF on Pi 1/2 (see bot.hwinfo) — a web server is exactly the kind
of always-on overhead a tiny board shouldn't carry. On a Pi 4/5 or a real
server it gives you an at-a-glance panel without opening Discord.

Read-only by design: it surfaces health + recent moderation events but takes no
destructive actions (that's what the DM console is for). Access is gated by a
shared token passed as ``?token=`` or an ``X-Token`` header.
"""

from __future__ import annotations

import html

from aiohttp import web

from .config import WebadminConfig


class WebAdmin:
    def __init__(self, bot) -> None:
        self.bot = bot
        self.cfg: WebadminConfig = bot.cfg.webadmin
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        if not self.cfg.enabled or not self.cfg.token:
            return
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/api/status", self._api_status)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.cfg.host, self.cfg.port)
        await site.start()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    def _authed(self, request: web.Request) -> bool:
        token = request.query.get("token") or request.headers.get("X-Token", "")
        return bool(self.cfg.token) and token == self.cfg.token

    async def _api_status(self, request: web.Request) -> web.Response:
        if not self._authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(self.bot.metrics.snapshot())

    async def _index(self, request: web.Request) -> web.Response:
        if not self._authed(request):
            return web.Response(
                text="Unauthorized. Append ?token=YOUR_TOKEN to the URL.",
                status=401,
            )
        s = self.bot.metrics.snapshot()
        rows = await self.bot.db.fetchall(
            "SELECT ts, kind, action, reason FROM mod_events ORDER BY ts DESC LIMIT 20"
        )
        ev = "".join(
            f"<tr><td>{html.escape(r['kind'] or '')}</td>"
            f"<td>{html.escape(r['action'] or '')}</td>"
            f"<td>{html.escape((r['reason'] or '')[:80])}</td></tr>"
            for r in rows
        )
        temp = s["cpu_temp_c"]
        temp_str = f"{temp:.1f}°C" if temp is not None else "n/a"
        body = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Pi Bot</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#0d1117;color:#c9d1d9}}
.wrap{{max-width:760px;margin:0 auto;padding:20px}}
h1{{font-size:1.3rem}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px}}
.k{{color:#8b949e;font-size:.8rem}} .v{{font-size:1.2rem;font-weight:600}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:.85rem}}
td,th{{border-bottom:1px solid #21262d;padding:6px;text-align:left}}
.meta{{color:#8b949e;font-size:.75rem;margin-top:20px}}
</style></head><body><div class=wrap>
<h1>🍓 Pi Bot dashboard</h1>
<div class=grid>
<div class=card><div class=k>Uptime</div><div class=v>{s['uptime_s']/3600:.1f} h</div></div>
<div class=card><div class=k>CPU temp</div><div class=v>{temp_str}</div></div>
<div class=card><div class=k>Loop lag</div><div class=v>{s['loop_lag_ms']} ms</div></div>
<div class=card><div class=k>Memory</div><div class=v>{s['mem_used_pct']}%</div></div>
<div class=card><div class=k>Guilds</div><div class=v>{s['guilds']}</div></div>
<div class=card><div class=k>Gateway</div><div class=v>{s['latency_ms']} ms</div></div>
<div class=card><div class=k>Mod actions</div><div class=v>{s['mod_actions']}</div></div>
<div class=card><div class=k>LLM breaker</div><div class=v>{'OPEN' if s['llm_breaker_open'] else 'ok'}</div></div>
</div>
<h2 style="font-size:1rem;margin-top:22px">Recent moderation</h2>
<table><tr><th>kind</th><th>action</th><th>reason</th></tr>{ev or '<tr><td colspan=3>none</td></tr>'}</table>
<div class=meta>Read-only. Auto-refreshes every 15s. Actions live in the Discord DM console.</div>
</div><script>setTimeout(()=>location.reload(),15000)</script></body></html>"""
        return web.Response(text=body, content_type="text/html")
