#!/usr/bin/env bash
#
# OS hardening — turns the box into a self-contained appliance (the Mail-in-a-
# Box idea). Safe defaults, and deliberately careful about SSH so a first-time
# user can't lock themselves out.
#
#   sudo bash scripts/harden.sh              # interactive
#   sudo bash scripts/harden.sh --unattended # no prompts, conservative choices
#
set -euo pipefail
c_g='\033[0;32m'; c_y='\033[1;33m'; c_0='\033[0m'
ok()   { echo -e "${c_g}  ✓${c_0} $*"; }
warn() { echo -e "${c_y}  !${c_0} $*"; }
say()  { echo -e "\033[1;34m==>${c_0} $*"; }

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
UNATTENDED=0; [ "${1:-}" = "--unattended" ] && UNATTENDED=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
export DEBIAN_FRONTEND=noninteractive

# read ports we may need to open
WEBADMIN_ENABLED=false; WEBADMIN_PORT=8086
[ -f "$APP_DIR/.env" ] && source <(grep -E '^(WEBADMIN_ENABLED|WEBADMIN_PORT)=' "$APP_DIR/.env" || true)

# ---- 1. automatic security updates ---------------------------------------- #
say "Enabling automatic security updates…"
apt-get install -y -qq unattended-upgrades apt-listchanges >/dev/null
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
# auto-reboot for kernel updates at 4am (messages can wait; uptime of the OS matters)
sed -i 's#//\s*Unattended-Upgrade::Automatic-Reboot "false";#Unattended-Upgrade::Automatic-Reboot "true";#' \
    /etc/apt/apt.conf.d/50unattended-upgrades 2>/dev/null || true
sed -i 's#//\s*Unattended-Upgrade::Automatic-Reboot-Time "02:00";#Unattended-Upgrade::Automatic-Reboot-Time "04:00";#' \
    /etc/apt/apt.conf.d/50unattended-upgrades 2>/dev/null || true
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
ok "unattended security updates on"

# ---- 2. firewall ----------------------------------------------------------- #
say "Configuring firewall (ufw)…"
apt-get install -y -qq ufw >/dev/null
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
# detect the live SSH port so we never fence ourselves out
SSH_PORT="$(grep -E '^Port ' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}' | head -1)"
SSH_PORT="${SSH_PORT:-22}"
ufw allow "${SSH_PORT}/tcp" >/dev/null
ok "allowed SSH on ${SSH_PORT}"
if [ "${WEBADMIN_ENABLED:-false}" = "true" ]; then
  ufw allow "${WEBADMIN_PORT}/tcp" >/dev/null
  ok "allowed web dashboard on ${WEBADMIN_PORT}"
fi
# Zabbix agent (only if installed); metrics/LLM stay bound to localhost.
if systemctl list-unit-files 2>/dev/null | grep -q 'zabbix-agent'; then
  ufw allow 10050/tcp >/dev/null && ok "allowed Zabbix agent on 10050"
fi
ufw --force enable >/dev/null
ok "firewall active (default deny incoming)"

# ---- 3. fail2ban ----------------------------------------------------------- #
say "Installing fail2ban (SSH brute-force protection)…"
apt-get install -y -qq fail2ban >/dev/null
cat >/etc/fail2ban/jail.d/sshd.local <<EOF
[sshd]
enabled = true
port = ${SSH_PORT}
maxretry = 5
bantime = 1h
EOF
systemctl enable --now fail2ban >/dev/null 2>&1 || true
ok "fail2ban guarding SSH"

# ---- 4. SSH hardening (carefully) ----------------------------------------- #
say "Hardening SSH…"
SSHD=/etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSHD"
sed -i 's/^#\?X11Forwarding.*/X11Forwarding no/' "$SSHD"
# Only disable password auth if keys exist AND the user opts in — else we could
# lock a beginner out of their own Pi. Never do this unattended.
have_keys=0
for home in /home/* /root; do
  [ -s "$home/.ssh/authorized_keys" ] && have_keys=1
done
if [ "$have_keys" -eq 1 ] && [ "$UNATTENDED" -eq 0 ]; then
  read -r -p "  SSH keys found. Disable password login (recommended, but keep a key handy)? (y/N) " a || a=n
  if [[ "$a" =~ ^[Yy] ]]; then
    sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD"
    ok "password login disabled (key-only)"
  else
    warn "left password login enabled"
  fi
else
  warn "left password login enabled (no keys found or unattended) — add an SSH key, then re-run to lock it down"
fi
systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || true
ok "SSH hardened"

# ---- 5. kernel/network sysctl --------------------------------------------- #
say "Applying sysctl hardening…"
cat >/etc/sysctl.d/99-pibot-hardening.conf <<'EOF'
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.all.accept_source_route=0
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.tcp_syncookies=1
kernel.kptr_restrict=1
EOF
sysctl -q --system >/dev/null 2>&1 || true
ok "sysctl applied"

# ---- 6. time sync ---------------------------------------------------------- #
timedatectl set-ntp true 2>/dev/null || true
ok "NTP time sync on"

echo
ok "Hardening complete. This box now auto-patches, firewalls, and bans brute-forcers."
warn "Keep an SSH session open and verify you can reconnect before closing this one."
