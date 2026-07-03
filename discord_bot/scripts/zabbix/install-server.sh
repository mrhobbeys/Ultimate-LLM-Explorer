#!/usr/bin/env bash
#
# Install a Zabbix SERVER on THIS box — only for capable hardware (Pi 4/5 with
# 4GB+, or a real server). A Zabbix server pulls in a database + web frontend +
# poller and is far too heavy for a Pi 1/2/3; bot.hwinfo gates the offer.
#
# This is guided rather than fully hands-off: the database step wants a couple
# of decisions only you should make (credentials), so we install the packages
# and print the exact remaining commands.
#
set -euo pipefail
c_g='\033[0;32m'; c_y='\033[1;33m'; c_0='\033[0m'
ok(){ echo -e "${c_g}  ✓${c_0} $*"; }; warn(){ echo -e "${c_y}  !${c_0} $*"; }
say(){ echo -e "\033[1;34m==>${c_0} $*"; }
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

# refuse on clearly-too-small hardware even if invoked directly
MEM_MB=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
CORES=$(nproc)
if [ "$MEM_MB" -lt 3500 ] || [ "$CORES" -lt 4 ]; then
  warn "This box has ${MEM_MB}MB / ${CORES} cores — too small for a Zabbix server."
  warn "Install the agent instead (install-agent.sh) and run the server elsewhere."
  exit 1
fi

. /etc/os-release 2>/dev/null || true
say "Adding the Zabbix package repository for ${ID:-debian} ${VERSION_CODENAME:-}…"
ZBX_VER="6.0"
REL_DEB="zabbix-release_${ZBX_VER}-1+${ID:-debian}${VERSION_ID:-12}_all.deb"
URL="https://repo.zabbix.com/zabbix/${ZBX_VER}/${ID:-debian}/pool/main/z/zabbix-release/${REL_DEB}"
if curl -fsSL -o "/tmp/${REL_DEB}" "$URL" 2>/dev/null; then
  dpkg -i "/tmp/${REL_DEB}" >/dev/null 2>&1 || true
  apt-get update -qq
  ok "Zabbix repo added"
else
  warn "Couldn't fetch the Zabbix repo .deb automatically."
  warn "Grab the right one from https://www.zabbix.com/download and 'dpkg -i' it, then re-run."
  exit 1
fi

say "Installing Zabbix server (SQLite-free stack uses MySQL/MariaDB)…"
apt-get install -y -qq mariadb-server zabbix-server-mysql zabbix-frontend-php \
    zabbix-apache-conf zabbix-sql-scripts zabbix-agent2 >/dev/null
ok "packages installed"

cat <<'EOF'

────────────────────────────────────────────────────────────────────
 Zabbix server packages are installed. Finish the database setup:

 1) Create the DB + user (choose your own password):
      sudo mysql -uroot <<SQL
      create database zabbix character set utf8mb4 collate utf8mb4_bin;
      create user zabbix@localhost identified by 'CHANGE_ME';
      grant all privileges on zabbix.* to zabbix@localhost;
      set global log_bin_trust_function_creators = 1;
      SQL

 2) Import the schema:
      zcat /usr/share/zabbix-sql-scripts/mysql/server.sql.gz \
        | sudo mysql --default-character-set=utf8mb4 -uzabbix -p zabbix

 3) Put the same password in /etc/zabbix/zabbix_server.conf (DBPassword=)

 4) Start it:
      sudo systemctl restart zabbix-server zabbix-agent2 apache2
      sudo systemctl enable  zabbix-server zabbix-agent2 apache2

 5) Open http://<this-host>/zabbix  (default login: Admin / zabbix)

 6) Import the bot template: scripts/zabbix/template_pibot.yaml
────────────────────────────────────────────────────────────────────
EOF
ok "Server install staged — complete the DB steps above."
