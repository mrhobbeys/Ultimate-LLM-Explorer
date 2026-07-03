"""Progression scaffolding: XP, ranks, and objectives.

This is intentionally a *foundation* — enough to make growth real (objectives
complete as you do IR work, XP accrues, you rank up) and extensible (new
scenarios / "levels" register their own objective sets). It stores everything
in the player's ``flags`` JSON, so no schema changes are needed to add more.

Wiring: the engine sets simple boolean event flags (``found_webshell`` etc.)
as the player acts; ``sync`` reads those, marks objectives done, awards XP, and
reports anything newly completed so the engine can surface a toast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

Flags = dict


@dataclass(frozen=True)
class Objective:
    id: str
    title: str
    xp: int
    predicate: Callable[[Flags], bool]
    hint: str = ""


@dataclass(frozen=True)
class Scenario:
    """A single 'level' — a box to investigate with its own objective set. Only
    one ships today (``dc01``); the registry is here so more can be added."""

    id: str
    name: str
    objectives: tuple[Objective, ...]


def _flag(name: str) -> Callable[[Flags], bool]:
    return lambda f: bool(f.get(name))


DC01_OBJECTIVES: tuple[Objective, ...] = (
    Objective("recon", "Log in and open a terminal on the DC", 10, _flag("opened_terminal"),
              "Log in at the desktop, then open the Command Prompt."),
    Objective("beacon", "Confirm the C2 beacon (running process / connection)", 15,
              _flag("found_beacon"), "Try tasklist and netstat."),
    Objective("runkey", "Find Run-key persistence", 15, _flag("found_runkey"),
              "reg query the HKLM ...\\Run key."),
    Objective("schtask", "Find the scheduled-task beacon", 15, _flag("found_schtask"),
              "Try schtasks."),
    Objective("webshell", "Locate the IIS webshell", 20, _flag("found_webshell"),
              "Look under C:\\inetpub\\wwwroot\\uploads and the IIS logs."),
    Objective("victim", "Interview patient zero", 10, _flag("interviewed_victim"),
              "Talk to Karen in Accounting."),
    Objective("creds", "Recover the staged Domain-Admin credentials", 20,
              _flag("found_creds"), "Attackers stash creds in config files."),
    Objective("escalate", "Escalate to Domain Admin", 25, _flag("escalated"),
              "runas /user:meridian\\svc_backup once you have the creds."),
    Objective("exfil", "Identify the data-exfiltration channel", 20, _flag("found_exfil"),
              "netstat for the outbound session; find the staged archive."),
    Objective("report", "Deliver your findings to the CISO", 30, _flag("wrote_report"),
              "Use the 'report' action on the desktop."),
)

SCENARIOS: dict[str, Scenario] = {
    "dc01": Scenario("dc01", "MERIDIAN-DC01 Intrusion", DC01_OBJECTIVES),
}

# Rank thresholds by total XP. Ranks are the "levels" the player grows through.
RANKS: tuple[tuple[int, str], ...] = (
    (0, "Tier-1 Analyst"),
    (40, "Tier-2 Analyst"),
    (90, "Tier-3 Analyst"),
    (150, "Incident Lead"),
    (200, "Lead IR / Threat Hunter"),
)


def rank_for(xp: int) -> tuple[int, str]:
    """Return (level_index starting at 1, rank name) for a given XP total."""
    level = 1
    name = RANKS[0][1]
    for i, (threshold, rank_name) in enumerate(RANKS):
        if xp >= threshold:
            level = i + 1
            name = rank_name
    return level, name


def next_rank(xp: int) -> tuple[str, int] | None:
    for threshold, rank_name in RANKS:
        if xp < threshold:
            return rank_name, threshold - xp
    return None


@dataclass
class SyncResult:
    newly_completed: list[Objective]
    leveled_up: tuple[int, str] | None  # (new level, rank name) if rank increased


def sync(flags: Flags, scenario_id: str = "dc01") -> SyncResult:
    """Reconcile objectives against event flags, award XP, and detect rank-ups.

    Mutates ``flags`` in place: ``flags['objectives']`` (dict id->True),
    ``flags['xp']`` (int), ``flags['level']`` (int). Returns what changed so the
    caller can show the player a toast.
    """
    scenario = SCENARIOS.get(scenario_id, SCENARIOS["dc01"])
    done: dict = flags.setdefault("objectives", {})
    xp = int(flags.get("xp", 0))
    prev_level, _ = rank_for(xp)

    newly: list[Objective] = []
    for obj in scenario.objectives:
        if done.get(obj.id):
            continue
        if obj.predicate(flags):
            done[obj.id] = True
            xp += obj.xp
            newly.append(obj)

    flags["xp"] = xp
    new_level, rank_name = rank_for(xp)
    flags["level"] = new_level
    leveled = (new_level, rank_name) if new_level > prev_level else None
    return SyncResult(newly_completed=newly, leveled_up=leveled)


def status_lines(flags: Flags, scenario_id: str = "dc01") -> list[str]:
    """Human-readable progress block for the `status` action."""
    scenario = SCENARIOS.get(scenario_id, SCENARIOS["dc01"])
    xp = int(flags.get("xp", 0))
    level, rank = rank_for(xp)
    done: dict = flags.get("objectives", {})
    lines = [f"Rank: {rank} (Level {level})   XP: {xp}"]
    nxt = next_rank(xp)
    if nxt:
        lines.append(f"Next rank: {nxt[0]} in {nxt[1]} XP")
    total = len(scenario.objectives)
    complete = sum(1 for o in scenario.objectives if done.get(o.id))
    lines.append(f"Case: {scenario.name}  —  Objectives {complete}/{total}")
    lines.append("")
    for obj in scenario.objectives:
        mark = "✅" if done.get(obj.id) else "⬜"
        lines.append(f"  {mark} {obj.title}  (+{obj.xp} XP)")
    return lines
