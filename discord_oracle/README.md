# Oracle — the compromised-server text adventure (a discord.py cog)

A self-contained Discord bot that drops players onto **MERIDIAN-DC01**, a
compromised Windows domain controller, and lets them work it like a real
incident-response analyst. It has two modes that flow into each other, a
**persistent, permission-aware Windows filesystem**, NPCs who **remember your
conversations**, and a light **XP / rank / objectives** progression system.

It runs **fully offline and free** — no API key required. An optional LLM backend
(a free local model via Ollama, or the paid Anthropic API) only makes the
character dialogue freeform; nothing else depends on it.

> This is a standalone subproject. It lives entirely in `discord_oracle/` and
> shares nothing with the rest of the repository.

## The two modes

**Mode one — the GUI / desktop.** The bot narrates screens and always gives you
an **Options** list to pick from:

```
🪟  Desktop — meridian\jmartin
You're on the Windows desktop. The taskbar has Outlook, Teams, Edge, the
ticket system, and a Command Prompt shortcut.  •  📧 1 unread from Dana (CISO)

Options
  `terminal` — open the Command Prompt (drops into the live shell)
  `ticket`   — open the incident ticket (your assignment)
  `email` / `chat` — talk to your boss and coworkers
  `report`   — write up and submit your findings
  `status`   — your rank, XP, and objectives
```

You log in (`login`), read the incident ticket, and talk to people — your CISO
(Dana), a senior IR colleague (Raj), and patient zero (Karen in Accounting).

**Mode two — the shell.** Opening the Command Prompt from the desktop drops you
into a real command line on the box. Type `exit` to return to the desktop. The
filesystem is **stateful**: `move` a file and it stays moved; `del` it and it's
gone — per player, forever, because each player gets their own copy of the
server.

## It behaves like a *real* box

This is the part that makes people forget it's a simulation.

- **`cmd` vs PowerShell are different, on purpose.** In `cmd`, `cp`/`ls`/`cat`
  are *not* commands:
  ```
  C:\Windows\System32> cp utilman.exe CMd.exe
  'cp' is not recognized as an internal or external command,
  operable program or batch file.
  ```
  Type `powershell` and those aliases resolve to `Copy-Item`/`Get-ChildItem`/etc.
  The difference *is* the lesson.
- **Case-insensitive** paths and commands (`CMd.exe`, `C:/Windows/System32`, `DIR`).
- **ACLs and privilege.** `C:\Windows\System32` is protected. As the compromised
  user you get `Access is denied.`; only after you **escalate** (a real milestone —
  find the staged Domain-Admin creds, then
  `runas /user:meridian\svc_backup`) do writes there succeed. That escalation *is*
  the classic utilman/sethc persistence technique, learned hands-on.
- **A simulated network.** `ping`, `tracert`, `nslookup`, `netstat`, `arp`,
  `curl`/`Invoke-WebRequest` run against a segmented enterprise LAN — internal
  hosts answer, external egress is blocked at the perimeter firewall, and one
  suspicious IP is the attacker's exfil endpoint.
- **Faithful errors** everywhere: `The system cannot find the file specified.`,
  `The syntax of the command is incorrect.`, `The directory is not empty.`, etc.

The scenario is a complete, learnable intrusion: initial-access lure, an
obfuscated PowerShell loader, Run-key + scheduled-task persistence, an IIS
webshell, staged Domain-Admin credentials, and outbound C2/exfil. Finding and
reasoning about these completes objectives and ranks you up from **Tier-1
Analyst** toward **Lead IR**.

## Was there a package to reuse?

No. The closest reusable pieces are `pyfakefs` (fakes a filesystem for tests, but
has no cmd/PowerShell semantics, ACLs, or network) and assorted toy "fake shell"
repos. None give you a persistent, permission-aware Windows box wired to a
progression system and an optional oracle. So this is built from scratch — but
built to behave.

## Run it

```bash
pip install -r discord_oracle/requirements.txt        # just discord.py
export DISCORD_TOKEN=your-bot-token                    # from the Discord dev portal
python -m discord_oracle.bot
```

Enable the **Message Content Intent** for your bot in the Discord developer
portal — the immersive session router reads plain messages.

In Discord:

```
!oracle start      → begin (or resume); your messages now go straight to the box
!oracle stop       → pause (world is saved)
!oracle status     → rank, XP, objectives
!oracle reset      → wipe your world and start a fresh compromise
!oracle whereami   → reprint the current screen
```

Once started, **just type** — `login`, `terminal`, `dir`, `talk raj`, whatever.
No prefix needed inside a session.

## Optional LLM enrichment (all free-first)

The game is fully playable with no LLM. To make NPC replies freeform, pick one:

- **Free / local (Ollama):** install [Ollama](https://ollama.com), then set
  `ORACLE_LLM_BACKEND=ollama` (optionally `ORACLE_OLLAMA_MODEL=llama3.1`).
- **Paid API (Anthropic):** set `ANTHROPIC_API_KEY`. Model defaults to
  `claude-opus-4-8`; use `ORACLE_MODEL=claude-haiku-4-5` for cheaper chatter.

See `.env.example` for every knob. If the LLM is off, errors, or times out, NPCs
fall back to their rule-based dialogue — they still remember what you told them.

## Architecture

Everything except `cog.py` and `bot.py` is Discord-free and unit-tested:

| Module           | Responsibility |
|------------------|----------------|
| `state.py`       | SQLite persistence — one isolated world per player |
| `filesystem.py`  | Windows path resolution, node ops, ACL checks |
| `shell.py`       | `cmd` + PowerShell dialects, faithful command output |
| `network.py`     | Simulated LAN for ping/tracert/nslookup/netstat/arp |
| `world.py`       | The seed filesystem (IR artifacts) + the cast |
| `npc.py`         | Persistent NPC memory + rule-based / LLM dialogue |
| `progression.py` | XP, ranks, objectives; scenario registry for future levels |
| `narrative.py`   | Mode-one screens and their options |
| `engine.py`      | Orchestration, mode switching, flag → objective wiring |
| `llm.py`         | Optional backend (none / Ollama / Anthropic) |
| `cog.py` / `bot.py` | discord.py integration |

## Extending it (levels / growth)

Progression is scaffolding you can grow into. New "levels" are new
`Scenario`s in `progression.py` (each an objective set) paired with a new world
seed in `world.py`. XP, ranks, and objective tracking already work off the
player's `flags` JSON, so adding a second box doesn't touch the schema.

## Tests

```bash
pip install pytest pytest-asyncio
cd discord_oracle && python -m pytest -q     # 25 tests, no network/LLM needed
```
