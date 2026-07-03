"""Server personality presets.

The owner shouldn't have to reason about ``suspicion_high`` and
``profanity_action``. They should say "this is a family server" or "this is a
gamer lounge" and get a sensible bundle of settings. These presets are that
translation layer — funny names, obvious meaning, concrete knobs.

Apply with the ``preset`` command or during ``setup``. Everything a preset sets
is a normal per-guild setting, so owners can still fine-tune afterward.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _thresholds(level: float) -> tuple[float, float]:
    """Same dial the `mod sensitivity` command uses (0 relaxed → 1 twitchy)."""
    low = round(0.4 * (1 - level) + 0.05, 3)
    high = round(0.9 * (1 - level) + 0.3, 3)
    return low, high


@dataclass
class Preset:
    key: str
    emoji: str
    name: str
    blurb: str
    sensitivity: float
    mod_mode: str
    profanity_action: str        # delete | warn | timeout | log
    llm_escalation: bool
    spam_max_messages: int
    min_account_age_hours: int
    raid_action: str
    extra: dict[str, str] = field(default_factory=dict)

    def settings(self) -> dict[str, str]:
        low, high = _thresholds(self.sensitivity)
        out = {
            "mod.mode": self.mod_mode,
            "mod.suspicion_low": str(low),
            "mod.suspicion_high": str(high),
            "mod.profanity_action": self.profanity_action,
            "mod.llm_escalation": "true" if self.llm_escalation else "false",
            "spam.max_messages": str(self.spam_max_messages),
            "raid.min_account_age_hours": str(self.min_account_age_hours),
            "raid.action": self.raid_action,
            "server.preset": self.key,
        }
        out.update(self.extra)
        return out


PRESETS: dict[str, Preset] = {
    p.key: p
    for p in [
        Preset(
            key="wildwest", emoji="🤠", name="Wild West",
            blurb="Anything goes. Only scams, raids, and truly nasty stuff get touched. "
                  "Trash talk and cussing are the house language.",
            sensitivity=0.1, mod_mode="armed", profanity_action="log",
            llm_escalation=False, spam_max_messages=10,
            min_account_age_hours=0, raid_action="log",
        ),
        Preset(
            key="gamer", emoji="🎮", name="Gamer Lounge",
            blurb="Cussing and banter are fine — but slurs, harassment, and scammers "
                  "get bounced. Friendly fire on, hate speech off.",
            sensitivity=0.45, mod_mode="approve", profanity_action="log",
            llm_escalation=True, spam_max_messages=8,
            min_account_age_hours=0, raid_action="lockdown",
        ),
        Preset(
            key="clean", emoji="🧼", name="Keep It Clean",
            blurb="Gamers welcome, but watch your mouth — swearing gets zapped, "
                  "harassment gets you a talking-to.",
            sensitivity=0.6, mod_mode="armed", profanity_action="delete",
            llm_escalation=True, spam_max_messages=6,
            min_account_age_hours=0, raid_action="lockdown",
        ),
        Preset(
            key="family", emoji="👨‍👩‍👧", name="Family Friendly",
            blurb="PG-rated. Profanity, nastiness, and sketchy links all get removed. "
                  "New accounts wait a day before joining.",
            sensitivity=0.75, mod_mode="armed", profanity_action="delete",
            llm_escalation=True, spam_max_messages=5,
            min_account_age_hours=24, raid_action="lockdown",
        ),
        Preset(
            key="fellowship", emoji="✝️", name="Fellowship Hall",
            blurb="Warm, welcoming, and squeaky clean. Strict filtering, kindness "
                  "encouraged, trolls shown the door.",
            sensitivity=0.85, mod_mode="armed", profanity_action="delete",
            llm_escalation=True, spam_max_messages=5,
            min_account_age_hours=24, raid_action="lockdown",
        ),
        Preset(
            key="fortknox", emoji="🔒", name="Fort Knox",
            blurb="Lockdown. Aggressive filtering, 3-day new-account gate, everything "
                  "logged. For servers under active attack or zero-tolerance.",
            sensitivity=0.92, mod_mode="armed", profanity_action="delete",
            llm_escalation=True, spam_max_messages=4,
            min_account_age_hours=72, raid_action="lockdown",
        ),
    ]
}

# order for display
ORDER = ["wildwest", "gamer", "clean", "family", "fellowship", "fortknox"]


def resolve(name: str) -> Preset | None:
    n = name.lower().strip().replace(" ", "").replace("-", "")
    if n in PRESETS:
        return PRESETS[n]
    # allow matching by display name
    for p in PRESETS.values():
        if p.name.lower().replace(" ", "") == n:
            return p
    return None


def summary_line(p: Preset) -> str:
    return f"{p.emoji} **{p.name}** (`{p.key}`) — {p.blurb}"
