"""The orchestrator. Owns state transitions between mode one (GUI/desktop) and
mode two (shell), routes input, sets progression event-flags from what the
player actually does, and returns a structured Response the cog renders.

All game state lives in the Store; the engine is otherwise stateless and safe to
share. A single lock serializes access to the SQLite connection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from . import narrative, progression
from .filesystem import VirtualFS, normalize
from .llm import LLM
from .shell import Shell
from .state import Player, Store
from .world import CREDS_PATH, NPCS, instantiate_world


@dataclass
class Response:
    kind: str  # 'shell' | 'scene' | 'system'
    body: str = ""
    title: str | None = None
    options: list[str] = field(default_factory=list)
    toasts: list[str] = field(default_factory=list)
    prompt: str | None = None
    echo: str | None = None


class Engine:
    def __init__(self, store: Store, llm: LLM | None = None) -> None:
        self.store = store
        self.llm = llm or LLM()
        self._lock = asyncio.Lock()

    # ---- lifecycle -----------------------------------------------------
    def ensure_player(self, player_key: str, guild_id: str | None, user_id: str) -> Player:
        player = self.store.get_player(player_key)
        if player is None:
            player = self.store.create_player(player_key, guild_id, user_id)
            instantiate_world(self.store, player_key)
        return player

    def reset_player(self, player_key: str, guild_id: str | None, user_id: str) -> Player:
        self.store.delete_world(player_key)
        player = self.store.create_player(player_key, guild_id, user_id)
        instantiate_world(self.store, player_key)
        return player

    def _prompt(self, player: Player) -> str:
        prefix = "PS " if player.dialect == "powershell" else ""
        return f"{prefix}{player.cwd}>"

    def opening_scene(self, player: Player) -> Response:
        if player.mode == "shell":
            return Response(kind="shell", prompt=self._prompt(player),
                            body="(You're at the terminal. Type `exit` to return to the desktop.)")
        scene = self._scene_for(player)
        return self._scene_response(scene, [])

    # ---- top-level dispatch -------------------------------------------
    async def handle(self, player_key: str, raw: str) -> Response:
        async with self._lock:
            player = self.store.get_player(player_key)
            if player is None:
                return Response(kind="system", body="No active session. Start one first.")
            if player.mode == "shell":
                return self._handle_shell(player, raw)
            return await self._handle_adventure(player, raw)

    # ---- mode two: shell ----------------------------------------------
    def _handle_shell(self, player: Player, raw: str) -> Response:
        shell = Shell(self.store, VirtualFS(self.store, player.player_key), player)
        result = shell.run(raw)

        # Persist mutable player state the shell may have changed.
        self._set_flags_from_shell(player, raw, result.output)
        toasts = self._advance(player)
        self.store.update_player(
            player.player_key, cwd=player.cwd, dialect=player.dialect,
            privilege=player.privilege, flags=player.flags,
        )

        if result.signal == "exit_to_desktop":
            player.mode = "adventure"
            player.location = "desktop"
            self.store.update_player(player.player_key, mode="adventure", location="desktop")
            scene = narrative.desktop_screen(player.flags)
            return self._scene_response(scene, toasts, extra="(You close the terminal.)")

        output = "" if result.output.startswith("\x00CLS") else result.output
        return Response(
            kind="shell", echo=raw, body=output,
            prompt=self._prompt(player), toasts=toasts,
        )

    def _set_flags_from_shell(self, player: Player, raw: str, output: str) -> None:
        flags = player.flags
        low = raw.strip().lower()
        cmd = low.split()[0] if low.split() else ""
        out = output.lower()

        if cmd in ("tasklist", "netstat"):
            flags["found_beacon"] = True
        if cmd == "netstat":
            flags["found_exfil"] = True
        if cmd == "reg" and "run" in low and "query" in low:
            flags["found_runkey"] = True
        if cmd == "schtasks":
            flags["found_schtask"] = True
        if "shell.aspx" in out:
            flags["found_webshell"] = True
        if "runas_pass" in out or "runas_user=meridian" in out:
            flags["found_creds"] = True
        if "accounting_export.7z" in out or "185.220.101.44" in out and cmd == "netstat":
            flags["found_exfil"] = True
        if player.privilege in ("admin", "system"):
            flags["escalated"] = True

        # Reading the creds file by any means also flips the gate.
        if cmd in ("type", "cat", "gc", "get-content", "more"):
            parts = raw.split()
            if len(parts) >= 2:
                target = normalize(parts[-1].strip('"'), player.cwd)
                if target.lower() == CREDS_PATH.lower():
                    flags["found_creds"] = True

    # ---- mode one: GUI / desktop --------------------------------------
    async def _handle_adventure(self, player: Player, raw: str) -> Response:
        low = raw.strip().lower()
        loc = player.location

        if loc.startswith("talk:"):
            return await self._handle_conversation(player, raw, loc.split(":", 1)[1])

        if loc == "login":
            if low in ("login", "log in", "signin", "sign in", "enter", "unlock"):
                player.location = "desktop"
                self.store.update_player(player.player_key, location="desktop")
                return self._scene_response(narrative.desktop_screen(player.flags), [])
            return self._scene_response(narrative.login_screen(), [],
                                        extra="(Type `login` to sign in.)")

        if loc in ("apps:email", "apps:chat"):
            return await self._handle_apps(player, low)

        if loc == "browser":
            if low in ("back", "desktop", "exit"):
                return self._go_desktop(player)
            return self._scene_response(narrative.browser_screen(), [])

        if loc == "ticket":
            if low in ("terminal", "cmd", "command prompt", "shell"):
                return self._enter_terminal(player)
            if low in ("back", "desktop", "exit"):
                return self._go_desktop(player)
            return self._scene_response(narrative.ticket_screen(), [])

        if loc == "report":
            if low in ("submit", "send"):
                player.flags["wrote_report"] = True
                toasts = self._advance(player)
                self.store.update_player(player.player_key, flags=player.flags)
                return self._go_desktop(
                    player, toasts,
                    extra="Dana: Got the report. Clear, well-evidenced. We'll start "
                          "eradication and rotate credentials tonight. Good work.",
                )
            if low in ("back", "desktop", "exit"):
                return self._go_desktop(player)
            return self._scene_response(narrative.report_screen(player.flags), [])

        # default: desktop
        return self._desktop_route(player, low)

    def _desktop_route(self, player: Player, low: str) -> Response:
        if low in ("terminal", "cmd", "command prompt", "shell", "console"):
            return self._enter_terminal(player)
        if low in ("ticket", "tickets", "incident"):
            return self._goto(player, "ticket", narrative.ticket_screen())
        if low in ("email", "outlook", "mail"):
            return self._goto(player, "apps:email", narrative.people_screen("email"))
        if low in ("chat", "teams", "message", "im"):
            return self._goto(player, "apps:chat", narrative.people_screen("chat"))
        if low in ("browser", "edge", "web", "intranet"):
            return self._goto(player, "browser", narrative.browser_screen())
        if low in ("report", "findings"):
            return self._goto(player, "report", narrative.report_screen(player.flags))
        if low in ("status", "progress", "objectives", "level", "xp"):
            return self._status_scene(player)
        if low in ("logoff", "logout", "lock", "signout", "sign out"):
            player.location = "login"
            self.store.update_player(player.player_key, location="login")
            return self._scene_response(narrative.login_screen(), [])
        if low in ("help", "?", "menu"):
            return self._scene_response(narrative.desktop_screen(player.flags), [],
                                        extra="Pick one of the options below by typing the word in backticks.")
        # Direct-talk shortcut from the desktop.
        if low.startswith("talk ") and low.split()[1] in NPCS:
            return self._start_conversation(player, low.split()[1])
        return self._scene_response(narrative.desktop_screen(player.flags), [],
                                    extra=f"'{low}' isn't an option here. Try one of the choices below.")

    async def _handle_apps(self, player: Player, low: str) -> Response:
        if low in ("back", "desktop", "exit"):
            return self._go_desktop(player)
        target = low[5:].strip() if low.startswith("talk ") else low
        if target in NPCS:
            return self._start_conversation(player, target)
        kind = "email" if player.location == "apps:email" else "chat"
        return self._scene_response(narrative.people_screen(kind), [],
                                    extra="Type `talk <name>` (dana, raj, or karen), or `back`.")

    def _start_conversation(self, player: Player, npc_id: str) -> Response:
        npc = NPCS[npc_id]
        player.location = f"talk:{npc_id}"
        # Mark first-contact milestones.
        flag = {"dana": "met_dana", "raj": "met_raj", "karen": "interviewed_victim"}[npc_id]
        player.flags[flag] = True
        toasts = self._advance(player)
        self.store.update_player(player.player_key, location=player.location, flags=player.flags)
        return Response(
            kind="scene", title=f"💬  {npc.name} — {npc.title}",
            body=npc.greeting, options=narrative.in_conversation_scene(npc.name),
            toasts=toasts,
        )

    async def _handle_conversation(self, player: Player, raw: str, npc_id: str) -> Response:
        low = raw.strip().lower()
        if low in ("back", "bye", "leave", "exit", "goodbye"):
            return self._go_desktop(player, extra=f"(You end the conversation.)")
        from . import npc as npc_mod

        npc = NPCS[npc_id]
        reply = await npc_mod.respond(self.store, player.player_key, npc, raw, self.llm)
        return Response(
            kind="scene", title=f"💬  {npc.name}", body=reply,
            options=narrative.in_conversation_scene(npc.name),
        )

    # ---- helpers -------------------------------------------------------
    def _enter_terminal(self, player: Player) -> Response:
        player.mode = "shell"
        player.location = "desktop"
        player.flags["opened_terminal"] = True
        toasts = self._advance(player)
        self.store.update_player(
            player.player_key, mode="shell", location="desktop", flags=player.flags
        )
        banner = (
            "Microsoft Windows [Version 10.0.17763.5458]\n"
            "(c) 2018 Microsoft Corporation. All rights reserved.\n\n"
            "(You're on MERIDIAN-DC01. This is a real shell — try what you'd type on a "
            "Windows box. `help` for a starter list, `exit` to return to the desktop.)"
        )
        return Response(kind="shell", body=banner, prompt=self._prompt(player), toasts=toasts)

    def _goto(self, player: Player, location: str, scene: narrative.Scene) -> Response:
        player.location = location
        self.store.update_player(player.player_key, location=location)
        return self._scene_response(scene, [])

    def _go_desktop(self, player: Player, toasts: list[str] | None = None,
                    extra: str | None = None) -> Response:
        player.location = "desktop"
        self.store.update_player(player.player_key, location="desktop")
        return self._scene_response(narrative.desktop_screen(player.flags), toasts or [], extra=extra)

    def _scene_for(self, player: Player) -> narrative.Scene:
        loc = player.location
        if loc == "login":
            return narrative.login_screen()
        if loc == "ticket":
            return narrative.ticket_screen()
        if loc == "browser":
            return narrative.browser_screen()
        if loc == "report":
            return narrative.report_screen(player.flags)
        if loc == "apps:email":
            return narrative.people_screen("email")
        if loc == "apps:chat":
            return narrative.people_screen("chat")
        return narrative.desktop_screen(player.flags)

    def _status_scene(self, player: Player) -> Response:
        lines = progression.status_lines(player.flags)
        lines.append("")
        lines.append(self.llm.describe())
        return Response(
            kind="scene", title="📈  Analyst Status", body="\n".join(lines),
            options=["`back` — return to the desktop"],
        )

    def _advance(self, player: Player) -> list[str]:
        """Reconcile objectives and return toast lines for anything new."""
        result = progression.sync(player.flags)
        toasts: list[str] = []
        for obj in result.newly_completed:
            toasts.append(f"✅ Objective complete: {obj.title}  (+{obj.xp} XP)")
        if result.leveled_up:
            level, rank = result.leveled_up
            toasts.append(f"⭐ Rank up! You are now **{rank}** (Level {level}).")
        return toasts

    def _scene_response(self, scene: narrative.Scene, toasts: list[str],
                        extra: str | None = None) -> Response:
        body = scene.body
        if extra:
            body = f"{body}\n\n{extra}"
        return Response(
            kind="scene", title=scene.title, body=body,
            options=scene.options, toasts=toasts,
        )
