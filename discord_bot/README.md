# 🍓 Pi Discord Bot

A full-featured, self-hosting Discord bot built to run on an **original
Raspberry Pi or Pi 2** — and to double as a testbed for how far that old
hardware can be pushed. It installs like an appliance (one command, guided
onboarding, OS hardening, auto-updates, monitoring), moderates intelligently
(deterministic first, offboard-LLM only for the uncertain middle), and can be
run entirely from your DMs.

It's also an exploration tool for `discord.py` — live event tailing, object
inspection, gateway introspection, hot cog-reload.

---

## Why `discord.py` (and not something lighter)?

**Stick with `discord.py`.** It's the best-documented library, which is what
matters most for a learning/exploration tool, and it runs fine on both Pis for
small servers. The real Pi 1 constraints are (1) ~60–90 MB Python baseline RAM
and (2) single-core zlib decompression of gateway payloads — both fine at small
scale. `hikari` is lighter/faster but steeper; only worth it if you're packing
many bots onto one Pi 1.

The bot is designed around those constraints:

- **Tiny core dependency set** — `discord.py` + `python-dotenv`. `aiohttp` (used
  for the LLM client, metrics server and web dashboard) ships *with* discord.py,
  so nothing extra. On a Pi 1 (ARMv6) with no prebuilt wheels, the installer
  detects the arch and compiles from source automatically.
- **Everything heavy is opt-in** — NLTK, the web dashboard, message logging, and
  the LLM are all flags. On a Pi 1 they default off; on a Pi 4/5 they default on.
- **No inference on the Pi** — the LLM lives on another box; the Pi only routes.

---

## Features

| Area | What it does |
|------|--------------|
| **Spam protection** | Sliding-window rate limits, duplicate detection, mention/link/emoji/newline floods |
| **Smart moderation** | Deterministic profanity (leet-normalized) → suspicion score → offboard LLM only for the ambiguous middle. The LLM's output never hits chat; it only informs delete/timeout/ban |
| **Learned spam filter** | Old-school email-style Naive Bayes that learns what spam *feels like* on **your** server. Trained by verified outcomes only (LLM verdicts, your DM approvals/denials, `!mod trainspam`) — never by its own catches, so no feedback loop. The more it learns, the fewer LLM calls you pay for. Microseconds per message, even on a Pi 1 |
| **DM approval** | In `approve` mode the bot DMs you *"ban so-and-so? Approve/Deny"* with buttons; decisions survive restarts |
| **Remote DM console** | Admins run the whole server from DMs: list users, pull someone's recent messages, ban/kick/timeout/delete/purge — without opening the server |
| **Raid & scam defense** | Join-velocity raid detection, new-account gating, phishing-link + nitro-scam filter, warn→mute→kick→ban ladder |
| **Ranking** | XP, levels, level-roles, reputation, badges, weekly digest, leaderboard |
| **Record-keeping** | Mirror edits/deletes/joins/leaves (and optionally every message) to a log channel + SQLite, with retention pruning |
| **Search helper** | Turns friendly flags into Discord search strings (`from:` `has:` `before:` …) |
| **Personality presets** | One command sets the whole moderation vibe: 🤠 Wild West · 🎮 Gamer Lounge · 🧼 Keep It Clean · 👨‍👩‍👧 Family Friendly · ✝️ Fellowship Hall · 🔒 Fort Knox |
| **Monitoring** | Local `/metrics` + `/healthz`, a status file, and a Zabbix agent template (server too, on capable hardware) |
| **Web dashboard** | Optional read-only status page (only on Pi 4/5+) |
| **Explore** | Live message tailing, object inspection, gateway stats, hot reload |
| **Melt-the-Pi harness** | Offline load generator + `bench`/`health` to find the throughput/thermal ceiling |

---

## Quick start

```bash
git clone <your-fork> && cd Ultimate-LLM-Explorer/discord_bot
sudo bash scripts/install.sh
```

The installer:

1. **Detects your hardware** and picks a profile (minimal / standard / full).
2. Installs system packages (and a build toolchain on ARMv6).
3. Creates a venv + a locked-down `pibot` service user.
4. Runs the **onboarding wizard** (token, USB offload, moderation vibe, LLM,
   web dashboard, email, hardening, monitoring).
5. Installs systemd units: the bot, a **daily backup**, and a **daily
   auto-update** timer.
6. Optionally **hardens the OS** and installs the **Zabbix agent**.

Flags: `--harden`, `--zabbix`, `--nltk`, `--skip-onboard`, `--unattended`.

> **Discord setup:** create an application at
> <https://discord.com/developers/applications>, add a Bot, enable the
> **Message Content** and **Server Members** privileged intents, and copy the
> token into onboarding.

Run without installing (for development):

```bash
pip install -r requirements.txt
cp .env.example .env         # fill in DISCORD_TOKEN + BOT_OWNER_IDS
python -m bot
```

---

## Moderation modes

Set per server with `!mod mode <mode>` (default `approve`):

- **off** — do nothing
- **shadow** — log what it *would* do, touch no one (great for tuning)
- **approve** — DM the owner for kicks/bans; delete/timeout happen immediately
- **armed** — everything automatic at the configured thresholds

One dial to tune strictness: `!mod sensitivity 0.7` (0 relaxed → 1 twitchy).
Instant freeze: `!panic on` pauses *all* automatic enforcement; `!panic off`
resumes. Manual/DM commands still work while paused.

## SD-card longevity (USB offload)

Write endurance is the #1 killer of a 24/7 Pi. During onboarding, answer **yes**
to *"put I/O-heavy tasks on a USB drive?"* and the wizard will detect a drive
(prompting you to insert one if needed), mount it, make it persistent in
`/etc/fstab` (by UUID, with `noatime,nofail`), and point the database/logs/
backups at it. On some Pis the USB bus is shared with ethernet — for a small,
low-traffic server that's a non-issue, and messages can wait.

## Monitoring with Zabbix

Run the **agent** on the Pi (light); host the **server** elsewhere — unless your
hardware is beefy (Pi 4/5 with 4 GB+), in which case onboarding offers to host
the server locally too. The bot writes a status snapshot that a UserParameter
reads:

```bash
zabbix_get -s 127.0.0.1 -k pibot.metric[cpu_temp_c]
```

Import `scripts/zabbix/template_pibot.yaml` on your Zabbix server for items +
triggers (temp > 80 °C, event-loop lag > 250 ms, LLM breaker open, …).

## Watch it melt 🔥

```bash
python scripts/stress.py --seconds 30 --workers 4 --csv melt.csv
```

Pushes synthetic messages through the *real* analysis pipeline as fast as it
can and reports msgs/sec plus the CPU-temperature climb. In Discord, `!health`
shows a live dashboard and `!bench` times the analyzer on the current hardware.

---

## Command reference (prefix `!` by default)

**Everyone:** `help` · `ping` · `rank [@user]` · `leaderboard` · `rep @user` ·
`search <flags>` · `searchhelp`

**Staff:** `mod` · `mod mode` · `mod sensitivity` · `mod test` ·
`mod trainspam` / `trainham` · `mod filter` · `warn` · `warnings` ·
`clearwarns` · `preset [name]`

**Admin:** `setup` · `set <key> <value>` · `get [key]` · `keys` · `panic` ·
`backup`

**Owner:** `inspect` · `tail [#channel]` · `gateway` · `reload <cog>` · `bench`

**DM console (admins):** `guilds` · `use <server>` · `users [query]` ·
`recent @user [n]` · `ban` · `kick` · `timeout` · `delete` · `purge` · `say`

---

## Architecture

```
bot/
  core.py        Bot subclass — wires config, db, settings, llm, metrics, webadmin
  config.py      env-driven config (every heavy feature behind a flag)
  db.py          SQLite on one dedicated thread — zero extra dependency
  settings.py    per-guild overlay (multi-tenant: one process, many servers)
  analysis.py    message "shapes", profanity, escalation decision (NLTK optional)
  llm.py         offboard OpenAI-compatible router (queue + breaker + LRU cache)
  metrics.py     event-loop lag sampler, /metrics + /healthz, status file
  webadmin.py    optional read-only dashboard (capable hardware only)
  mailer.py      stdlib SMTP notifications
  hwinfo.py      hardware detection + profile-driven defaults
  presets.py     server personality presets
  onboard.py     CLI onboarding wizard
  cogs/          logs, spam, moderation, remote, raid, ranking, search,
                 helpcog, explore, health, admin
scripts/         install.sh, harden.sh, update.sh, setup-usb.sh, stress.py, zabbix/
systemd/         service + backup timer + auto-update timer
```

Multi-tenant by design: one process serves many guilds, each with its own
settings — the key to hosting many small servers on one board. Upgrade the
instance when a server outgrows it.

## Development

```bash
make install    # venv + deps + dev tools
make test       # pytest (pure logic, no Discord needed)
make run        # run the bot from .env
make stress     # melt-the-Pi harness
make hwinfo     # print detected hardware profile
```

## Privacy & safety notes

- Message logging is **off by default**; when on, `LOG_RETENTION_DAYS` prunes
  old rows. Tell your members what you log.
- The web dashboard is read-only and token-gated.
- Start in `shadow` (or the default `approve`) mode and tune before going
  `armed`. The bot never moderates staff.
