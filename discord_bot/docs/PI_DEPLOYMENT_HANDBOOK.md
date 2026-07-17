# Raspberry Pi Deployment Handbook

**A project-agnostic guide to running always-on services on Raspberry Pi
hardware (including the very oldest boards), and to designing an onboarding
experience that turns a bare Pi into a self-maintaining appliance.**

> **Status: living document.** These learnings come from designing and
> building a real always-on service targeted at the original Pi 1 / Pi 2.
> Everything here has been reasoned through and bench-tested off-device;
> real-hardware results should be added to the *Field Notes* section at the
> bottom as testing happens. When a claim gets confirmed or corrected on real
> hardware, update it in place and note it.

---

## 1. Know your hardware before you write a line of code

The Pi name covers ~15 years of wildly different machines. Design decisions
that are correct on a Pi 5 are fatal on a Pi 1. Classify first:

| Class | Boards | Arch | RAM | Cores | Honest capability |
|---|---|---|---|---|---|
| **Minimal** | Pi 1, Pi Zero | ARMv6 | 256–512 MB | 1 | One lean service. No web UI, no local ML, nothing "extra" |
| **Standard** | Pi 2, Pi 3, Zero 2 W | ARMv7/v8 | 512 MB–1 GB | 4 | A real service + monitoring agent + light extras |
| **Full** | Pi 4, Pi 5, non-Pi servers | ARMv8/x86 | 2–16 GB | 4+ | Whatever you want, within reason |

Detect at install time, not in documentation. The three reliable sources on
Linux, all readable with zero dependencies:

- `/proc/device-tree/model` — exact board name ("Raspberry Pi 2 Model B Rev 1.1")
- `/proc/meminfo` `MemTotal` — the honest RAM ceiling
- `platform.machine()` / `uname -m` — the architecture (`armv6l` is the flag
  that changes everything; see §3)

Fold these into a single **capability profile** (minimal / standard / full)
and derive *every* default from the profile: which features are on, worker
counts, cache sizes, whether a web UI is even offered. One detection module,
consumed by the installer, the onboarding wizard, and the app itself, keeps
all three consistent.

**Design rule: the profile opens and closes options.** Don't ask a Pi 1 user
whether they want the web dashboard — tell them their hardware shouldn't host
one (and let them override if they insist). On a Pi 5, default it on. The
user should feel the installer *knows what it's standing on*.

## 2. The three things that actually kill a Pi (none of them are CPU)

Everyone worries about CPU. In practice an always-on Pi dies from these,
in this order:

### 2.1 SD-card write endurance — the #1 killer

Consumer microSD cards tolerate a limited number of writes, and a 24/7
service that logs, journals, and checkpoints will chew through cheap cards in
months. Every design decision that reduces writes extends the deployment's
life:

- **SQLite in WAL mode with `synchronous=NORMAL`** — batches writes, keeps
  readers non-blocking, dramatically fewer sync operations than the default.
- **`noatime` on every mount** — otherwise every *read* causes a metadata
  *write*.
- **Make the firehose opt-in.** Whatever your equivalent of "log every event"
  is, ship it OFF. Log the summaries and the exceptional events by default.
- **Retention pruning as a built-in, not a chore.** A daily job that deletes
  rows older than N days bounds both disk usage and privacy exposure.
- **Offload the data directory to USB storage** (§6.3). USB flash still
  wears, but a $10 stick is sacrificial and swappable; corrupting the *boot
  medium* takes the whole box down.
- **Atomic writes for status files** — write to a temp file and `rename()`,
  so a power cut never leaves a half-written file.

### 2.2 RAM exhaustion

- A bare Python 3 process with a networking library loaded starts at
  **60–90 MB RSS**. On a 256 MB board the OS takes ~50 MB, so your budget for
  *everything else* is roughly 100 MB. This single number drives most of the
  architecture in §4.
- **Cap every unbounded structure at construction time**: message/object
  caches, dedup windows, learned-model vocabularies, verdict caches. Anything
  that grows with traffic needs a cap and an eviction rule (LRU, prune-
  singletons, sliding windows that delete empty keys).
- Swap on SD is not a safety net — it's a slow-motion crash *and* it burns
  the card (§2.1). Treat hitting swap as an outage.

### 2.3 Thermal throttling

- Pi SoCs throttle around **80–85 °C**. Sustained load on passively cooled
  boards gets there faster than people expect.
- Read `/sys/class/thermal/thermal_zone0/temp` (integer millidegrees, no
  dependencies) and export it as a first-class metric with an alert at 80 °C.
- Load-test *for the temperature curve*, not just the throughput number: run
  a sustained stress and log temp once per second to CSV. The shape (how fast
  it climbs, where it plateaus) tells you whether a case/heatsink is needed
  long before production traffic does.

## 3. The ARMv6 software cliff (Pi 1 / original Zero)

`armv6l` is the architecture nobody builds for anymore. This is the most
common way an "it works on my Pi 4" project fails on a Pi 1:

- **Prebuilt wheels mostly don't exist.** PyPI wheels target ARMv7+; piwheels
  coverage of ARMv6 is partial and lags. `pip install` will silently fall
  back to **compiling from source**.
- **Compiling from source is fine — if you planned for it.** Install the
  toolchain up front (`build-essential python3-dev libffi-dev libssl-dev`),
  and *warn the user it will be slow*. A C-extension build that takes 40
  seconds on a laptop can take 30+ minutes on a Pi 1. The worst outcome is a
  user who thinks the install hung and pulls the plug — the message
  "this will compile and be slow, but it works" is part of the product.
- **Detect `armv6l` in the installer and branch**: add the toolchain, extend
  timeouts, print the warning. Don't make the user discover this.
- **The stronger move: need fewer dependencies.** Every dependency you don't
  have is a build that can't fail:
  - Prefer stdlib: `sqlite3` over a DB driver, `smtplib` over an email SDK,
    `re` + arithmetic over an NLP library.
  - Prefer pure-Python packages (no C extensions) when you must depend.
  - Reuse transitive dependencies you already carry (if your framework ships
    an HTTP client, use it for everything HTTP) instead of adding parallel ones.
  - Make genuinely heavy dependencies **optional at runtime** with graceful
    degradation: try-import, fall back to the cheap path, expose "is the
    heavy path active?" as a status field. Then the same codebase runs
    everywhere and the profile (§1) decides what lights up.

## 4. Architecture patterns for constrained hardware

### 4.1 Tiered processing: spend CPU like money

The single most important pattern. Arrange work so the cheap layer answers
almost everything and each escalation is deliberate:

1. **Tier 0 — deterministic and near-free** (regex, counters, arithmetic on
   the hot path). Target: handles 95%+ of events. Microseconds.
2. **Tier 1 — cheap learned models** (e.g. Naive Bayes over token counts:
   dict lookups + logs, still microseconds, learns the deployment's own
   patterns). Trained by the outcomes of the tiers around it, it steadily
   *steals traffic from Tier 2* — the system gets cheaper as it runs.
3. **Tier 2 — expensive/offboard** (LLM call, remote API). Only the genuinely
   ambiguous middle gets here. Everything about this tier is bounded: queue
   depth, concurrency, timeout.

Two numeric thresholds (below = ignore, above = act, between = escalate) make
the routing tunable per deployment with a single "sensitivity" dial.

Guard the learning loop: **never train a model on its own decisions** — only
on independently verified outcomes (the expensive tier's verdicts, human
approvals/denials, deterministic hits). Otherwise it amplifies its own
mistakes.

### 4.2 Offboard the heavy compute; the Pi routes

An old Pi should never run inference, transcoding, or bulk analytics. It
*routes* to a beefier box (LAN server, desktop with a GPU, cloud endpoint)
and acts on the result. The routing client needs, non-negotiably:

- **A concurrency cap** (1 worker on minimal hardware — never two expensive
  calls in flight).
- **A bounded queue** — drop-and-log beats memory growth when the backend
  falls behind.
- **A circuit breaker** — after N consecutive failures, stop calling for a
  cooldown (with backoff) so a dead backend doesn't wedge the hot path. The
  system must degrade to Tiers 0–1, not stall.
- **A result cache** (small LRU keyed on normalized input) — repeated inputs
  are common and a cache hit is a free expensive-tier answer.
- **Timeouts on everything.**

### 4.3 Storage: SQLite, one writer, no server

A database *server* (Postgres, MySQL, Redis) is another 50–200 MB resident —
that's the whole RAM budget on a minimal board. SQLite in WAL mode covers an
enormous range of workloads. A clean async-friendly pattern with zero extra
dependencies: one persistent connection owned by a **single-worker thread
pool**, every query routed through it via the event loop's executor. All
access serializes through one thread — no lock juggling, safe by
construction, and write pressure stays SD-card friendly.

Use SQLite's **online backup API** for backups: consistent snapshots while
the service runs, no downtime, no `.dump` gymnastics. Prune old backups on a
retention count.

### 4.4 One process, many tenants

Process count is the dominant cost on small hardware — each additional
Python process re-pays the 60–90 MB baseline. If the service will host
multiple customers/rooms/sites, make one process serve them all with
**per-tenant settings overlaid on global defaults** (a `(tenant, key, value)`
table, cached in memory, consulted through typed getters with the global
config as fallback). Per-process-per-tenant on a Pi 1 means ~1 tenant;
multi-tenant means dozens of small ones. "Upgrade your instance" then means
moving the tenant to bigger hardware, not re-architecting.

### 4.5 Event-loop lag is your canary

For any async service, the single best early-warning metric is **scheduler
lag**: ask the loop to wake you in exactly N seconds, measure how late the
wakeup fires. Healthy ≈ 0 ms. Rising lag means CPU saturation, a blocking
call sneaking onto the loop, or thermal throttling — visible *minutes before*
users feel it. It costs one background task and belongs in every health
readout with an alert around 250 ms.

### 4.6 Cap the framework, too

Frameworks default their internal caches for laptops. Find the knobs
(message/object cache sizes, connection pools, history buffers) and set them
from the hardware profile. This is often a bigger RAM lever than anything in
your own code.

## 5. Monitoring an appliance

- The service should expose **three cheap surfaces**, all from the same
  snapshot: `/healthz` (boolean, for restart logic), `/metrics`
  (text, for scrapers), and a **status file on disk** (JSON, atomically
  replaced every ~15 s).
- The status file is the trick that makes heavyweight monitoring integrable
  on tiny hardware: a monitoring **agent** (e.g. zabbix-agent2, ~10 MB)
  reads the file with a tiny helper script — no HTTP round-trip, no
  authentication complexity, works even when the service's HTTP is bound to
  localhost.
- **Run the monitoring server elsewhere.** A monitoring server (DB + web
  stack + pollers) is a heavier workload than most services being monitored.
  Only offer local hosting of it when detection says the hardware is truly
  capable (4 GB+ / 4 cores), and even then prefer remote.
- Ship an **importable template** (items + triggers) alongside the agent
  config so alerting works out of the box. Suggested trigger thresholds that
  have held up in design testing: CPU temp > 80 °C · loop lag > 250 ms ·
  memory > 92 % · expensive-tier circuit breaker open.
- Include app-level counters, not just system stats: events seen, actions
  taken, escalations, cache hits, backend failures/latency. The ratio
  "escalations : events" is the cost meter for the tiered architecture.

## 6. Onboarding design: the appliance model

The reference experience is Mail-in-a-Box: one command turns a fresh box
into a finished, self-maintaining product, with a guided setup a non-sysadmin
can complete — and every choice skippable and changeable later. The
principles that generalize:

### 6.1 One command, and the installer is smart

`sudo bash install.sh` does everything: system packages, service user, venv,
dependencies, systemd units, timers. **Hardware detection runs first** (§1)
and visibly announces what it found and which profile it chose — the user
should see "Board: pi_2 · Profile: STANDARD" before the first question. On
ARMv6 it adds the compiler toolchain and says, out loud, that pip will be
slow and that slow ≠ stuck.

### 6.2 Ask less by detecting more; make every question skippable

The wizard flow that works:

- **Lead with identity questions only the user can answer** (credentials,
  who is the admin).
- **Then one "what kind of deployment is this?" question** that maps to a
  named preset bundle, instead of ten knob questions. Users can answer "what
  is this place" instantly; they cannot answer "what threshold do you want."
  Give presets memorable names with one-line plain-language descriptions,
  and translate each into a full settings bundle. Fine-tuning individual
  knobs remains available *afterward*, for the users who want it.
- **Every wizard answer must have a non-wizard path.** Config file for every
  global; a runtime `set <key> <value>` command for every tenant setting.
  `--skip-onboard` and `--unattended` flags for fleet/scripted installs.
  The wizard is a convenience, never a gate — and it must be re-runnable.
- **Generate secrets; don't ask for them.** Dashboard tokens etc. should be
  minted (`secrets.token_urlsafe`) and printed, not requested.
- **Write the config from the annotated example file**, substituting the
  answered keys and leaving everything else present-but-commented. The
  config file doubles as the reference documentation.
- The wizard's system-level choices (harden? monitoring agent? monitoring
  server?) are written to a small choices file the installer consumes — so
  wizard and installer stay decoupled but consistent.

### 6.3 Guided hardware setup beats documented hardware setup

For the USB storage offload (§2.1), the flow that respects a non-sysadmin:

1. Ask the *why* question, not the *how*: "Put heavy writing on a USB drive
   to spare the SD card? (recommended)".
2. If yes → **detect** USB block devices (`lsblk` with transport filter).
3. If none found → **prompt to plug one in and rescan** (bounded retries),
   with a clean skip path.
4. Found → offer existing partitions or a format (formatting requires typing
   a confirmation word — destructive actions never hide behind a y/n).
5. Then **automate all of it**: mount, `/etc/fstab` entry **by UUID** with
   `noatime,nofail` (`nofail` so a yanked drive can't hang boot),
   permissions, directory layout.

The generalizable principle: *when setup requires touching hardware, the
software drives the loop — detect, instruct, wait, verify, automate — rather
than emitting a wiki link.*

### 6.4 Hardening is part of onboarding, with one iron rule

A non-sysadmin's box must end up secure without them knowing what fail2ban
is: automatic security updates (with scheduled auto-reboot for kernel
patches — "messages can wait" is the right trade for an appliance), default-
deny firewall opened only for detected needs, brute-force protection,
sane SSH and sysctl settings, a no-login system user owning the service,
systemd sandboxing (`NoNewPrivileges`, `ProtectSystem`, `ReadWritePaths`
limited to the data directory).

The iron rule: **never take an action that can lock the operator out.**
Detect the *live* SSH port before writing firewall rules. Never disable SSH
password auth unless (a) an authorized key is verifiably present and (b) the
user explicitly opts in — and never in unattended mode. End with "keep this
session open and verify you can reconnect."

### 6.5 The box maintains itself

- `Restart=always` with a rate-limit window — uptime is the product.
- A daily **auto-update timer**: fetch, fast-forward only (never merge/rebase
  surprises on an appliance), reinstall deps *only if the dependency file
  changed*, restart, notify. Non-fast-forward = leave it alone and say so.
- A daily **backup timer** using the online backup API, with retention.
- **Email notifications** via plain SMTP (stdlib — no dependency) for the
  events an absent operator cares about: updated, restarted, alert fired.
  Configured (or skipped) during onboarding: host, port, TLS, from/to.
- Jitter scheduled jobs (randomized delay) so a fleet doesn't thundering-herd.

### 6.6 Safety rails for the service itself

Two operational modes that cost little and save deployments:

- **Shadow / dry-run mode as the default posture** for anything that takes
  autonomous actions: log what *would* happen, touch nothing, until the
  operator has watched it and turns it up.
- **A panic switch**: one command that instantly pauses all automated
  actions (manual control stays live), one command to resume. When something
  misbehaves at 2 a.m., the operator needs a hand brake, not a config dive.

## 7. Testing methodology for constrained hardware

- **Build an offline stress harness** that pushes synthetic traffic through
  the real hot path (no network, no external service) as fast as possible,
  across N processes. Report msgs/sec and per-worker rate, and log
  temperature once per second to CSV for the thermal curve (§2.3).
- **Benchmark on the dev box first to set the yardstick.** Reference point
  from this project: the Tier-0 analysis pipeline ran ~27,000 msgs/sec on a
  4-core x86 dev container, ~13,600/worker. Expect an order of magnitude (or
  two) less on a Pi 1 — the ratio is the interesting number, and the point
  of testing is to find it.
- **Watch the canary metrics under load**, not just throughput: event-loop
  lag, RSS, temperature. The first one to move is your real bottleneck.
- **Test the install path on the real minimal board**, not just the app:
  ARMv6 compile times, RAM pressure during `pip`, wizard usability over a
  slow SSH session. The installer is part of the product surface.

## 8. Quick-reference checklist

**Before writing code**
- [ ] Define hardware profiles; write the detection module first
- [ ] Set the RAM budget from the smallest supported board; list every cache and its cap
- [ ] Choose dependencies by "will it build on ARMv6" and "can it be optional"

**Architecture**
- [ ] Tiered processing with tunable thresholds; expensive tier offboard
- [ ] Circuit breaker + bounded queue + cache + timeout on every external call
- [ ] SQLite WAL / single-writer; online-backup API; retention pruning
- [ ] Multi-tenant in one process with per-tenant settings overlay
- [ ] Event-loop lag sampler + status file + /metrics + /healthz

**Onboarding**
- [ ] One-command install; detection announces board + profile before questions
- [ ] Preset question instead of knob questions; every answer skippable & re-doable
- [ ] Guided USB offload (detect → prompt-insert → automate mount/fstab by UUID)
- [ ] Hardening on by default; zero lockout paths; unattended mode stays conservative
- [ ] Timers: backup, auto-update (ff-only), both jittered; SMTP notifications
- [ ] Shadow mode default; panic switch present

**Validation**
- [ ] Offline stress harness with temperature CSV
- [ ] Yardstick numbers recorded from dev hardware
- [ ] Full install rehearsed on the real minimal board

---

## Field Notes (update as real-world testing lands)

| Date | Board | What was tested | Result / correction to this doc |
|---|---|---|---|
| — | — | *(pending first hardware run)* | — |

Known open questions for the first hardware pass:

1. Actual ARMv6 `pip install` wall-clock for the core dependency set (and
   whether piwheels covers any of it).
2. Real Tier-0 throughput and temperature plateau on Pi 1 vs Pi 2 (stress
   harness, 60 s+ run).
3. RSS on the minimal profile after 24 h of uptime — do the caps hold?
4. Whether gateway/network reconnect behavior on flaky Wi-Fi needs its own
   backoff tuning.
5. USB-vs-SD latency impact on WAL commit times under bursts.
