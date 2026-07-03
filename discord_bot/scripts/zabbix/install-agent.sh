#!/usr/bin/env bash
#
# Install + configure zabbix-agent2 on the Pi to report bot + hardware metrics.
# The Zabbix SERVER must live elsewhere (never on a Pi 1/2) — this only sets up
# the lightweight agent and the UserParameters it needs.
#
set -euo pipefail
APP_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> Installing zabbix agent…"
if ! apt-get install -y -qq zabbix-agent2 >/dev/null 2>&1; then
  apt-get install -y -qq zabbix-agent >/dev/null 2>&1 || {
    echo "!! Could not install a zabbix agent from apt."
    echo "   Add Zabbix's repo (https://www.zabbix.com/download) and re-run."
    exit 1
  }
fi

# find the agent's include directory
INCLUDE_DIR=""
for d in /etc/zabbix/zabbix_agent2.d /etc/zabbix/zabbix_agentd.d; do
  [ -d "$d" ] && INCLUDE_DIR="$d"
done
[ -z "$INCLUDE_DIR" ] && { mkdir -p /etc/zabbix/zabbix_agent2.d; INCLUDE_DIR=/etc/zabbix/zabbix_agent2.d; }

# resolve the bot's status file path from its config
STATUS_FILE="$(cd "$APP_DIR" && python3 -c 'from bot.config import Config; print(Config.load().status_path)' 2>/dev/null || echo "$APP_DIR/data/status.json")"
echo "==> Bot status file: $STATUS_FILE"

# install the metric helper with the real status path baked in
sed "s#@STATUS@#$STATUS_FILE#g" "$HERE/pibot_metric.sh" > /etc/zabbix/pibot_metric.sh
chmod 0755 /etc/zabbix/pibot_metric.sh
cp "$HERE/userparameter_pibot.conf" "$INCLUDE_DIR/userparameter_pibot.conf"

echo "==> UserParameters installed to $INCLUDE_DIR"

# restart whichever agent is present
systemctl restart zabbix-agent2 2>/dev/null || systemctl restart zabbix-agent 2>/dev/null || true
systemctl enable zabbix-agent2 2>/dev/null || systemctl enable zabbix-agent 2>/dev/null || true

cat <<EOF

✅ Zabbix agent installed.

Next steps (on the Pi):
  1. Edit the agent config (Server=, ServerActive=, Hostname=) to point at your
     Zabbix server:  /etc/zabbix/zabbix_agent2.conf
  2. Restart:  sudo systemctl restart zabbix-agent2

On your Zabbix SERVER:
  3. Import the template:  scripts/zabbix/template_pibot.yaml
  4. Add this Pi as a host, attach the "Pi Discord Bot" template.

Test locally:
  zabbix_get -s 127.0.0.1 -k pibot.metric[cpu_temp_c]
EOF
