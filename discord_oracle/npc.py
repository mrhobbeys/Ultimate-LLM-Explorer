"""NPC dialogue. Characters remember every conversation (persisted per player),
so what you told the boss an hour ago is still true. Two paths:

  * Free/offline: keyword-matched replies from the character's script, colored by
    memory ("you mentioned the webshell earlier").
  * LLM-enriched: the same persona + case knowledge + recent memory handed to a
    local or API model for freeform replies. If that path errors or is disabled,
    we silently use the rule-based reply — the character never goes silent.
"""

from __future__ import annotations

from .llm import LLM
from .state import Store
from .world import NPC


CASE_BRIEF = (
    "Setting: incident response at Meridian Logistics. The domain controller "
    "MERIDIAN-DC01 was compromised on 2026-06-30. Known facts: initial access via "
    "a malicious 'invoice_Q2.pdf.exe' opened by Karen Osei in Accounting; a "
    "PowerShell loader (update.ps1) and implant (update.exe) in her AppData; a "
    "Run-key 'WinUpdate' and a scheduled task 'SystemUpdate' for persistence; an "
    "IIS webshell at C:\\inetpub\\wwwroot\\uploads\\shell.aspx; a Domain-Admin "
    "service account 'svc_backup' whose password was staged in "
    "C:\\ProgramData\\svc\\config.ini; and outbound C2/exfil to 185.220.101.44. "
    "The player is the analyst investigating. Stay in character. Keep replies to "
    "1-4 sentences. Never break the fourth wall or mention being an AI. Do not "
    "hand the player every answer at once — nudge, don't dump."
)


def greeting(npc: NPC) -> str:
    return npc.greeting


def _rule_based(npc: NPC, message: str, memory: list[tuple[str, str]]) -> str:
    low = message.lower()
    for key, reply in npc.responses.items():
        if key in low:
            return reply
    # Light memory awareness so repeat topics feel continuous.
    if any(key in low for key in ("what did i", "remember", "again")):
        for role, content in reversed(memory):
            if role == "player":
                return f"{npc.name.split()[0]}: Earlier you said: \"{content}\". Where do you want to take it?"
    return npc.fallback


def _system_prompt(npc: NPC) -> str:
    return (
        f"You are {npc.name}, {npc.title}. {npc.persona}\n\n{CASE_BRIEF}\n\n"
        f"Always answer as {npc.name}, prefixed with your first name and a colon."
    )


async def respond(
    store: Store,
    player_key: str,
    npc: NPC,
    message: str,
    llm: LLM,
) -> str:
    store.add_memory(player_key, npc.id, "player", message)
    memory = store.recent_memory(player_key, npc.id, limit=16)

    reply: str | None = None
    if llm.enabled:
        history = [
            {"role": "assistant" if role == "npc" else "user", "content": content}
            for role, content in memory
            if content != message
        ]
        reply = await llm.generate(_system_prompt(npc), history, message)

    if not reply:
        reply = _rule_based(npc, message, memory)

    store.add_memory(player_key, npc.id, "npc", reply)
    return reply
