# Migrating this repo to a self-hosted Gitea + local CI

This guide moves the project from GitHub to your local Gitea instance and
lights up CI on your own runner. It fits the project's philosophy: your code,
your hardware, your pipeline.

## 1. Migrate the repository

### Option A — Gitea's built-in migrator (recommended)

Gitea can pull the whole repo (history, branches, tags) straight from GitHub:

1. In Gitea: **+ ▸ New Migration ▸ GitHub**
2. URL: `https://github.com/mrhobbeys/Ultimate-LLM-Explorer`
3. If the GitHub repo is private, paste a GitHub personal access token
   (classic, `repo` scope) — Gitea uses it once for the clone. This also lets
   Gitea import issues/PR history if you tick those boxes.
4. Choose **Migration** (one-time copy) — or **Mirror** if you want Gitea to
   keep syncing from GitHub while you transition, then flip it to a normal
   repo later (Settings ▸ convert to regular repository).

### Option B — push from any clone (works offline)

```bash
git clone --mirror https://github.com/mrhobbeys/Ultimate-LLM-Explorer
cd Ultimate-LLM-Explorer.git
git push --mirror http://<gitea-host>:3000/<you>/Ultimate-LLM-Explorer.git
```

`--mirror` carries every branch and tag in one shot, including the
development branch with the open PR's commits.

### Re-point your working clones

```bash
git remote set-url origin http://<gitea-host>:3000/<you>/Ultimate-LLM-Explorer.git
# optional: keep GitHub reachable as a second remote
git remote add github https://github.com/mrhobbeys/Ultimate-LLM-Explorer
```

### Don't forget the open PR

Gitea's migrator can import PRs; a `--mirror` push cannot (PRs aren't refs
you can push). If you go with Option B, merge or re-open the draft PR by hand:
the branch arrives either way, so it's **New Pull Request ▸
`claude/discord-bot-legacy-pi-i8900g` → `main`** in the Gitea UI.

## 2. CI on your own runner

The workflow at `.github/workflows/ci.yml` **runs on Gitea unchanged**.
Gitea Actions is deliberately GitHub-Actions-compatible: same YAML, same
`actions/checkout` ecosystem (fetched via a configurable proxy, default
gitea.com's mirrors). When no `.gitea/workflows/` directory exists, Gitea
falls back to reading `.github/workflows/` — so one file serves both hosts
during the transition. If you later want Gitea-specific behavior, copy the
file to `.gitea/workflows/ci.yml` and diverge; Gitea will then prefer it.

### Enable Actions (once per Gitea instance)

In `app.ini`:

```ini
[actions]
ENABLED = true
```

then restart Gitea, and check the repo's **Settings ▸ Actions** is enabled.

### Register a runner

`act_runner` is a single static Go binary — it runs fine on a spare box, a
VM, or a Pi 3/4 class machine (see hardware note below):

```bash
# on the runner host
wget https://gitea.com/gitea/act_runner/releases/latest  # pick your arch
act_runner register \
  --instance http://<gitea-host>:3000 \
  --token <from Gitea: Site Admin ▸ Actions ▸ Runners ▸ Create token> \
  --labels ubuntu-latest:docker://catthehacker/ubuntu:act-latest
sudo ./act_runner daemon   # or install it as a systemd service
```

Notes that save an afternoon:

- **`runs-on` matches runner labels, not real OSes.** The label
  `ubuntu-latest` above maps to a Docker image; the workflow doesn't care.
- **Docker mode needs Docker on the runner host.** For a lighter setup,
  register a *host-mode* runner instead
  (`--labels system-python:host`) — jobs then run directly on the host with
  its system Python. The workflow already has a `test-system-python` job
  wired for exactly this label (manual-dispatch by default so it doesn't
  fail on setups without that runner).
- **`actions/setup-python` downloads toolchains** on first run per version —
  fine on x86/ARM64 with internet; not available for ARMv6. On minimal
  runners, use the host-mode lane instead.
- **Runner on a Pi:** act_runner itself is light, but the matrix (3 Python
  versions) triples the work. On small hardware, trim the matrix to the one
  Python version you deploy on — Bookworm's 3.11 — or rely on the
  host-mode lane only.

### What CI runs

- `compileall` over `bot/`, `scripts/`, `tests/` — catches syntax and
  import-level breakage everywhere, even in files without test coverage yet
- `pytest` (24 tests: analysis heuristics, presets, bayes filter learning)

Both are dependency-light on purpose (the project's only deps are
`discord.py` + `python-dotenv`), so a full CI run is minutes even on modest
runner hardware.

## 3. What changes for the deployed bots

The auto-update timer (`scripts/autoupdate.sh`) does `git fetch` +
fast-forward against `origin` — it follows whatever the clone's origin is.
On each deployed Pi:

```bash
sudo -u <botuser> git -C /opt/<install-dir> remote set-url origin \
  http://<gitea-host>:3000/<you>/Ultimate-LLM-Explorer.git
```

and auto-updates now flow from your Gitea. (If Gitea is HTTPS with a
self-signed cert, either add the CA to the Pi's trust store or use plain
HTTP on a trusted LAN — don't set `http.sslVerify=false` globally.)

## 4. A note on Claude Code sessions after migration

Cloud sessions (claude.ai/code, the GitHub app) can only reach GitHub — they
can't see a LAN-hosted Gitea. After migrating, run Claude Code as the local
CLI on a machine that can reach your Gitea; git push/pull, CI monitoring via
`tea` CLI or the Gitea API, and everything else works the same from there.
Keeping GitHub as a mirror (Option A's mirror mode, reversed: Gitea ▸ repo ▸
Settings ▸ Mirror Settings ▸ push mirror to GitHub) gives you both worlds —
local-first hosting, cloud-agent access when you want it.
