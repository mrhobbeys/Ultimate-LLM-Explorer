#!/usr/bin/env bash
# Zabbix UserParameter helper: read one metric out of the bot's status file.
# The status file path is baked in by install-agent.sh (replaces @STATUS@).
# Usage: pibot_metric.sh <metric_key>
STATUS_FILE="@STATUS@"
KEY="${1:-}"
[ -z "$KEY" ] && { echo "ZBX_NOTSUPPORTED"; exit 1; }
python3 - "$STATUS_FILE" "$KEY" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    val = data.get(sys.argv[2], "")
    if isinstance(val, bool):
        val = int(val)
    print("" if val is None else val)
except Exception:
    print("ZBX_NOTSUPPORTED")
PY
