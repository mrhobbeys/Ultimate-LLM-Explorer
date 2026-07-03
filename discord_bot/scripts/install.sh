#!/usr/bin/env bash
#
# One-command installer for the Pi Discord bot — the Mail-in-a-Box idea applied
# to a Discord bot. Turns a fresh Raspberry Pi (or any Debian/Ubuntu box) into a
# self-contained, auto-updating, monitored appliance. You do not need to be a
# sysadmin: answer a few questions and you're live.
#
#   sudo bash scripts/install.sh                 # interactive, safe defaults
#   sudo bash scripts/install.sh --harden        # also lock down the OS
#   sudo bash scripts/install.sh --zabbix        # also install the Zabbix agent
#   sudo bash scripts/install.sh --skip-onboard  # don't run the .env wizard
#   sudo bash scripts/install.sh --unattended    # no prompts at all
#
set -euo pipefail

# ---- pretty output --------------------------------------------------------- #
c_g='\033[0;32m'; c_y='\033[1;33m'; c_r='\033[0;31m'; c_b='\033[1;34m'; c_0='\033[0m'
say()  { echo -e "${c_b}==>${c_0} $*"; }
ok()   { echo -e "${c_g}  ✓${c_0} $*"; }
warn() { echo -e "${c_y}  !${c_0} $*"; }
die()  { echo -e "${c_r}  ✗ $*${c_0}" >&2; exit 1; }

# ---- args ------------------------------------------------------------------ #
DO_HARDEN=0; DO_ZABBIX=0; SKIP_ONBOARD=0; UNATTENDED=0; DO_NLTK=0
for a in "$@"; do case "$a" in
  --harden) DO_HARDEN=1 ;;
  --zabbix) DO_ZABBIX=1 ;;
  --skip-onboard) SKIP_ONBOARD=1 ;;
  --unattended) UNATTENDED=1; SKIP_ONBOARD=1 ;;
  --nltk) DO_NLTK=1 ;;
  *) die "unknown flag: $a" ;;
esac; done

[ "$(id -u)" -eq 0 ] || die "please run with sudo/root."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_USER="pibot"
VENV="$APP_DIR/.venv"

say "Installing from: $APP_DIR"

# ---- 0. detect hardware and choose a profile ------------------------------- #
say "Detecting hardware…"
eval "$(cd "$APP_DIR" && python3 -m bot.hwinfo --sh)"
echo -e "   Board: ${c_g}${HW_BOARD}${c_0}  Profile: ${c_g}${HW_PROFILE^^}${c_0}  " \
        "(${HW_CORES} cores, ${HW_MEM_MB} MB, ${HW_ARCH})"
echo "   ${HW_NOTES}"
# profile picks NLTK unless the user forced it on the CLI
[ "$DO_NLTK" -eq 0 ] && [ "$HW_ENABLE_NLTK" = "1" ] && DO_NLTK=1

# ---- 1. system packages ---------------------------------------------------- #
say "Installing system packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates >/dev/null
if [ "$HW_BUILD_FROM_SOURCE" = "1" ]; then
  warn "ARMv6 detected (Pi 1/Zero): no prebuilt wheels for some deps."
  warn "Installing build toolchain — the pip step will COMPILE and be slow, but it works."
  apt-get install -y -qq build-essential python3-dev libffi-dev libssl-dev libjpeg-dev zlib1g-dev >/dev/null
fi
ok "base packages installed"

# ---- 2. service user ------------------------------------------------------- #
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  ok "created service user '$SERVICE_USER'"
else
  ok "service user '$SERVICE_USER' exists"
fi

# ---- 3. python venv + deps ------------------------------------------------- #
say "Creating virtualenv and installing dependencies…"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"
if [ "$DO_NLTK" -eq 1 ]; then
  say "Installing optional NLTK extras (heavier — Pi 2 recommended)…"
  "$VENV/bin/pip" install -q -r "$APP_DIR/requirements-optional.txt"
  "$VENV/bin/python" -m nltk.downloader -q vader_lexicon punkt || warn "NLTK data download failed (offline?)"
fi
ok "dependencies installed"

# ---- 4. data dir + permissions -------------------------------------------- #
mkdir -p "$APP_DIR/data/backups"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data"
ok "data directory ready"

# ---- 5. onboarding (.env) -------------------------------------------------- #
if [ "$SKIP_ONBOARD" -eq 0 ]; then
  if [ -f "$APP_DIR/.env" ]; then
    warn ".env already exists — leaving it alone (rerun with the bot's 'setup' command to change settings)."
  else
    say "Launching onboarding wizard…"
    "$VENV/bin/python" -m bot.onboard || warn "onboarding skipped/failed; edit .env by hand"
  fi
else
  [ -f "$APP_DIR/.env" ] || cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  warn "onboarding skipped — edit $APP_DIR/.env and set DISCORD_TOKEN before starting."
fi
[ -f "$APP_DIR/.env" ] && chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env" && chmod 600 "$APP_DIR/.env"

# let onboarding choices drive hardening / zabbix (CLI flags still win)
if [ -f "$APP_DIR/.install-choices" ]; then
  # shellcheck disable=SC1090
  source "$APP_DIR/.install-choices"
  [ "$DO_HARDEN" -eq 0 ] && [ "${HARDEN:-0}" = "1" ] && DO_HARDEN=1
  [ "$DO_ZABBIX" -eq 0 ] && [ "${ZABBIX:-0}" = "1" ] && DO_ZABBIX=1
fi

# if data was relocated to USB, make sure the service user owns it
DATA_DIR="$(grep -E '^BOT_DATA_DIR=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
if [ -n "${DATA_DIR:-}" ] && [ "$DATA_DIR" != "data" ]; then
  mkdir -p "$DATA_DIR/backups"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
  ok "data relocated to $DATA_DIR (SD card spared)"
fi

# ---- 6. systemd service ---------------------------------------------------- #
say "Installing systemd service + backup timer…"
sed -e "s#@APP_DIR@#$APP_DIR#g" -e "s#@USER@#$SERVICE_USER#g" \
    "$APP_DIR/systemd/discord-bot.service" > /etc/systemd/system/discord-bot.service
sed -e "s#@APP_DIR@#$APP_DIR#g" -e "s#@USER@#$SERVICE_USER#g" \
    "$APP_DIR/systemd/discord-bot-backup.service" > /etc/systemd/system/discord-bot-backup.service
cp "$APP_DIR/systemd/discord-bot-backup.timer" /etc/systemd/system/discord-bot-backup.timer
sed -e "s#@APP_DIR@#$APP_DIR#g" \
    "$APP_DIR/systemd/discord-bot-update.service" > /etc/systemd/system/discord-bot-update.service
cp "$APP_DIR/systemd/discord-bot-update.timer" /etc/systemd/system/discord-bot-update.timer
systemctl daemon-reload
systemctl enable --now discord-bot-backup.timer >/dev/null 2>&1 || true
systemctl enable --now discord-bot-update.timer >/dev/null 2>&1 || true
ok "systemd units installed (service + daily backup + daily auto-update)"

# ---- 7. optional OS hardening --------------------------------------------- #
if [ "$DO_HARDEN" -eq 1 ]; then
  say "Hardening the OS (appliance mode)…"
  bash "$SCRIPT_DIR/harden.sh" ${UNATTENDED:+--unattended} || warn "hardening had issues; review output"
fi

# ---- 8. optional Zabbix agent / server ------------------------------------ #
if [ "$DO_ZABBIX" -eq 1 ]; then
  say "Installing Zabbix agent integration…"
  bash "$SCRIPT_DIR/zabbix/install-agent.sh" "$APP_DIR" || warn "zabbix agent setup had issues"
fi
if [ "${ZABBIX_SERVER:-0}" = "1" ] && [ "$HW_ENABLE_ZABBIX_SERVER" = "1" ]; then
  say "Installing Zabbix server (capable hardware detected)…"
  bash "$SCRIPT_DIR/zabbix/install-server.sh" || warn "zabbix server setup needs manual DB steps (see output)"
elif [ "${ZABBIX_SERVER:-0}" = "1" ]; then
  warn "Zabbix server requested but this hardware is too small — installed agent only."
fi

# ---- 9. start -------------------------------------------------------------- #
if grep -q "^DISCORD_TOKEN=.\+" "$APP_DIR/.env" 2>/dev/null; then
  systemctl enable --now discord-bot.service
  sleep 2
  systemctl --no-pager --lines=10 status discord-bot.service || true
  ok "bot started"
else
  warn "No DISCORD_TOKEN yet. Set it in $APP_DIR/.env then: sudo systemctl enable --now discord-bot"
fi

echo
ok "Done. Useful commands:"
echo "     journalctl -u discord-bot -f      # live logs"
echo "     systemctl restart discord-bot     # restart"
echo "     bash $SCRIPT_DIR/update.sh        # update + restart"
echo "     curl -s localhost:8085/status     # metrics snapshot"
