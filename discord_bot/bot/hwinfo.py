"""Hardware detection — the single source of truth for "what am I running on?"

Pure stdlib so it works *before* the venv or any dependency exists (the
installer calls it early). Classifies the board into a capability profile and
recommends feature defaults, so a Pi 1 doesn't try to host a web dashboard and
a Pi 5 isn't needlessly crippled.

    python3 -m bot.hwinfo            # human-readable
    python3 -m bot.hwinfo --json     # machine-readable
    python3 -m bot.hwinfo --sh       # KEY=VALUE for `eval` in shell
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import asdict, dataclass


def _model_string() -> str:
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            return open(path, "rb").read().decode(errors="ignore").strip("\x00").strip()
        except Exception:
            continue
    # fall back to cpuinfo
    try:
        for line in open("/proc/cpuinfo"):
            if line.lower().startswith(("model name", "hardware")):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.platform()


def _mem_total_mb() -> int:
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal"):
                return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def _classify_pi(model: str) -> str:
    m = model.lower()
    if "raspberry pi" not in m:
        return "non-pi"
    if "zero 2" in m:
        return "pi_zero2"
    if "zero" in m:
        return "pi_zero"
    for tag in ("pi 5", "pi 4", "pi 3", "pi 2"):
        if tag in m:
            return "pi_" + tag.split()[-1]
    if "pi model b" in m or "pi model a" in m or "pi 1" in m:
        return "pi_1"
    return "pi_unknown"


@dataclass
class HardwareInfo:
    model: str
    arch: str
    cores: int
    mem_mb: int
    board: str          # pi_1 / pi_2 / … / non-pi
    profile: str        # minimal | standard | full
    # recommendations
    enable_nltk: bool
    enable_webadmin: bool
    enable_metrics_http: bool
    enable_zabbix_server: bool   # host a full Zabbix server here? (capable HW only)
    worker_count: int
    message_cache: int
    build_from_source: bool
    notes: str

    def env_lines(self) -> list[str]:
        """Suggested .env defaults for this hardware."""
        return [
            f"BOT_ENABLE_NLTK={'true' if self.enable_nltk else 'false'}",
            f"WEBADMIN_ENABLED={'true' if self.enable_webadmin else 'false'}",
            f"METRICS_ENABLED={'true' if self.enable_metrics_http else 'false'}",
            f"LLM_MAX_WORKERS={1 if self.profile == 'minimal' else max(1, self.worker_count - 1)}",
        ]


def detect() -> HardwareInfo:
    model = _model_string()
    arch = platform.machine()
    cores = os.cpu_count() or 1
    mem = _mem_total_mb()
    board = _classify_pi(model)

    # ARMv6 (Pi 1 / Zero) rarely has prebuilt wheels → may need to compile.
    armv6 = arch in {"armv6l", "armv6"}
    build_from_source = armv6

    # profile by the tighter of RAM and board class
    if armv6 or mem and mem < 512 or board in {"pi_1", "pi_zero"}:
        profile = "minimal"
    elif (mem and mem <= 1200) or board in {"pi_2", "pi_3", "pi_zero2"}:
        profile = "standard"
    else:
        profile = "full"

    # a Zabbix *server* (DB + web + poller) is only sane with real RAM/cores.
    zabbix_server_ok = profile == "full" and (mem >= 3500) and cores >= 4

    if profile == "minimal":
        rec = dict(
            enable_nltk=False, enable_webadmin=False, enable_metrics_http=True,
            enable_zabbix_server=False, worker_count=1, message_cache=200,
            notes="Pi 1 / Zero class: keep it lean. No web UI, NLTK off, LLM "
                  "escalation throttled. Zabbix *agent* only — never a server here.",
        )
    elif profile == "standard":
        rec = dict(
            enable_nltk=False, enable_webadmin=False, enable_metrics_http=True,
            enable_zabbix_server=False, worker_count=max(1, cores - 1), message_cache=500,
            notes="Pi 2 / 3 class: comfortable for the bot + agent. NLTK optional. "
                  "A web dashboard is possible but not recommended — leave it off. "
                  "Zabbix agent only.",
        )
    else:
        rec = dict(
            enable_nltk=True, enable_webadmin=True, enable_metrics_http=True,
            enable_zabbix_server=zabbix_server_ok, worker_count=max(2, cores - 1),
            message_cache=1000,
            notes="Pi 4 / 5 or a server: enable the works — NLTK, web dashboard, and "
                  + ("you can host a Zabbix server here too." if zabbix_server_ok
                     else "the Zabbix agent (a full server wants 4GB+ / 4+ cores)."),
        )

    return HardwareInfo(
        model=model, arch=arch, cores=cores, mem_mb=mem, board=board,
        profile=profile, build_from_source=build_from_source, **rec,
    )


def main(argv: list[str]) -> int:
    info = detect()
    if "--json" in argv:
        print(json.dumps(asdict(info), indent=2))
    elif "--sh" in argv:
        for k, v in asdict(info).items():
            if isinstance(v, bool):
                v = "1" if v else "0"
            print(f"HW_{k.upper()}={v}")
    else:
        print(f"Model     : {info.model}")
        print(f"Arch      : {info.arch}  ({info.cores} cores, {info.mem_mb} MB RAM)")
        print(f"Board     : {info.board}")
        print(f"Profile   : {info.profile.upper()}")
        print(f"NLTK      : {'on' if info.enable_nltk else 'off'}")
        print(f"Web admin : {'on' if info.enable_webadmin else 'off'}")
        print(f"Build src : {'yes (ARMv6 — will compile, be patient)' if info.build_from_source else 'no'}")
        print(f"Notes     : {info.notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
