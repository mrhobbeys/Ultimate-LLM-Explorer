#!/usr/bin/env bash
#
# Self-update: pull latest code, refresh deps only if they changed, restart the
# service, and email the operator (if mail is configured). Safe to run from a
# systemd timer (--from-timer) or by hand.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$APP_DIR/.venv"
FROM_TIMER=0
[ "${1:-}" = "--from-timer" ] && FROM_TIMER=1

cd "$APP_DIR"

# repo root may be a parent of APP_DIR (discord_bot lives inside the repo)
GIT_DIR="$(git -C "$APP_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$APP_DIR")"
cd "$GIT_DIR"

before="$(git rev-parse HEAD 2>/dev/null || echo none)"
echo "==> Fetching updates (current: ${before:0:8})"
git fetch --quiet origin || { echo "fetch failed"; exit 0; }
branch="$(git rev-parse --abbrev-ref HEAD)"
git merge --ff-only "origin/$branch" --quiet || {
  echo "!! non-fast-forward; leaving working tree alone"; exit 0; }
after="$(git rev-parse HEAD)"

if [ "$before" = "$after" ]; then
  echo "==> Already up to date."
  exit 0
fi
echo "==> Updated ${before:0:8} -> ${after:0:8}"

# refresh deps only if requirements changed
if git diff --name-only "$before" "$after" | grep -q "requirements"; then
  echo "==> Dependencies changed; reinstalling…"
  "$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt" || echo "!! pip step failed"
fi

# restart the service if it's installed
if systemctl list-unit-files | grep -q '^discord-bot\.service'; then
  echo "==> Restarting service…"
  systemctl restart discord-bot.service || echo "!! restart failed"
fi

# notify via email if configured (best-effort)
changelog="$(git log --oneline "$before".."$after" | head -20)"
"$VENV/bin/python" -m bot.mailer \
  "Pi bot updated to ${after:0:8}" \
  "Updated from ${before:0:8} to ${after:0:8} on $(hostname).

$changelog" >/dev/null 2>&1 || true

echo "==> Update complete."
