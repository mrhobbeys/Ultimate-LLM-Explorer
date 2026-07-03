"""Interactive onboarding — writes .env, hardware-aware, nothing missed.

Run by the installer, or any time with ``python -m bot.onboard``. It detects
the board, proposes profile-appropriate defaults, and walks through every knob
that matters at deploy time. Anything you skip keeps a sane default and can be
changed later — globals by editing .env, per-server ones with the `set`
command in Discord.

It also writes ``.install-choices`` so the installer knows whether you asked
for OS hardening / the Zabbix agent.
"""

from __future__ import annotations

import secrets
import subprocess
import sys
from pathlib import Path

from .hwinfo import detect

APP_DIR = Path(__file__).resolve().parent.parent


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  (using default)")
        return default
    return val or default


def ask_bool(prompt: str, default: bool) -> bool:
    d = "Y/n" if default else "y/N"
    val = ask(f"{prompt} ({d})", "")
    if not val:
        return default
    return val.lower().startswith("y")


def warn(msg: str) -> None:
    print(f"  ! {msg}")


def _setup_usb() -> str | None:
    """Run the USB setup helper; return the chosen data dir or None."""
    script = APP_DIR / "scripts" / "setup-usb.sh"
    if not script.exists():
        return None
    import os
    import tempfile

    if os.geteuid() != 0:
        warn("USB auto-setup needs root — run the installer with sudo for the full flow.")
        return None
    with tempfile.NamedTemporaryFile("r", suffix=".env", delete=False) as tf:
        out_path = tf.name
    try:
        subprocess.run(["bash", str(script), out_path], check=False)
        for line in Path(out_path).read_text().splitlines():
            if line.startswith("PIBOT_DATA_DIR="):
                return line.split("=", 1)[1].strip()
    except Exception as exc:  # noqa: BLE001
        warn(f"USB setup failed: {exc}")
    finally:
        Path(out_path).unlink(missing_ok=True)
    return None


def list_mounts() -> list[str]:
    """Candidate external mounts (USB stick / SSD) to relocate data onto."""
    out = []
    try:
        res = subprocess.run(
            ["lsblk", "-rno", "MOUNTPOINT,TRAN"], capture_output=True, text=True, timeout=5
        )
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] in {"usb", "sata"} and parts[0].startswith("/"):
                out.append(parts[0])
    except Exception:
        pass
    for base in ("/media", "/mnt"):
        p = Path(base)
        if p.is_dir():
            out += [str(x) for x in p.glob("*/*") if x.is_dir()]
            out += [str(x) for x in p.glob("*") if x.is_dir()]
    return sorted(set(out))


def main() -> int:
    hw = detect()
    print("\n" + "=" * 60)
    print("  Pi Discord Bot — onboarding")
    print("=" * 60)
    print(f"  Detected: {hw.model}")
    print(f"  {hw.arch}, {hw.cores} cores, {hw.mem_mb} MB  →  profile: {hw.profile.upper()}")
    print(f"  {hw.notes}")
    print("-" * 60)
    print("  Press Enter to accept the [default]. Ctrl+C to bail.\n")

    env: dict[str, str] = {}

    # --- essentials ---
    print("· Discord credentials (from the Developer Portal → Bot):")
    env["DISCORD_TOKEN"] = ask("Bot token", secret=True)
    env["BOT_PREFIX"] = ask("Command prefix", "!")
    env["BOT_OWNER_IDS"] = ask("Your Discord user ID(s), space-separated")

    # --- storage / SD-card longevity ---
    print("\n· Storage — the SD card's write endurance is the #1 thing that kills")
    print("  a 24/7 Pi. Offloading the bot's writes (database, logs, backups) to a")
    print("  USB stick or SSD dramatically extends its life. Messages can wait, so")
    print("  the slightly slower USB bus is a non-issue on a small server.")
    if ask_bool("Put I/O-heavy tasks on a USB drive?", True):
        data_dir = _setup_usb()
        if data_dir:
            env["BOT_DATA_DIR"] = data_dir
        else:
            mounts = list_mounts()
            suggested = (mounts[0] + "/pibot-data") if mounts else "/mnt/usb/pibot-data"
            print("  (Auto-setup unavailable — falling back to a manual path.)")
            env["BOT_DATA_DIR"] = ask("Data directory", suggested)
    else:
        env["BOT_DATA_DIR"] = ask("Data directory", "data")

    # --- moderation ---
    print("\n· Moderation:")
    print("  off = nothing · shadow = log only · approve = DM you before bans · armed = auto")
    env["MOD_MODE"] = ask("Default moderation mode", "approve")
    env["BOT_ENABLE_NLTK"] = "true" if ask_bool(
        "Enable NLTK sentiment analysis? (heavier; ok on Pi 2+)", hw.enable_nltk
    ) else "false"

    # --- LLM routing ---
    print("\n· Local LLM routing (offboard — the Pi only routes, never infers):")
    if ask_bool("Use an offboard LLM for uncertain messages?", True):
        env["LLM_ENABLED"] = "true"
        env["LLM_BASE_URL"] = ask("OpenAI-compatible base URL", "http://127.0.0.1:11434/v1")
        env["LLM_MODEL"] = ask("Model name", "llama3.2:1b")
        key = ask("API key (blank for local servers)", "")
        if key:
            env["LLM_API_KEY"] = key
        env["LLM_MAX_WORKERS"] = "1" if hw.profile == "minimal" else str(max(1, hw.cores - 1))
    else:
        env["LLM_ENABLED"] = "false"

    # --- web dashboard (capable hardware only) ---
    print("\n· Web dashboard (read-only status page):")
    if hw.enable_webadmin:
        want_web = ask_bool("Enable the web dashboard on this hardware?", True)
    else:
        print("  (Your hardware is on the small side — a web server is not recommended here.)")
        want_web = ask_bool("Enable it anyway?", False)
    if want_web:
        env["WEBADMIN_ENABLED"] = "true"
        env["WEBADMIN_PORT"] = ask("Web dashboard port", "8086")
        token = secrets.token_urlsafe(16)
        env["WEBADMIN_TOKEN"] = token
        host_or_ip = ask("Public domain or IP for links (blank = none)", "")
        if host_or_ip:
            scheme = "https" if "." in host_or_ip and not host_or_ip[0].isdigit() else "http"
            env["WEBADMIN_PUBLIC_URL"] = f"{scheme}://{host_or_ip}:{env['WEBADMIN_PORT']}"
        print(f"  → Dashboard token generated: {token}")
        print(f"    Access at http://<host>:{env['WEBADMIN_PORT']}/?token={token}")
    else:
        env["WEBADMIN_ENABLED"] = "false"

    # --- email notifications ---
    print("\n· Email notifications (updates, restarts, alerts):")
    if ask_bool("Send email notifications?", False):
        env["MAIL_ENABLED"] = "true"
        env["MAIL_HOST"] = ask("SMTP host", "smtp.gmail.com")
        env["MAIL_PORT"] = ask("SMTP port", "587")
        env["MAIL_USERNAME"] = ask("SMTP username")
        env["MAIL_PASSWORD"] = ask("SMTP password / app-password", secret=True)
        env["MAIL_FROM"] = ask("From address", env.get("MAIL_USERNAME", ""))
        env["MAIL_TO"] = ask("Send notifications to (space-separated)", env.get("MAIL_FROM", ""))
        env["MAIL_NOTIFY_ON_UPDATE"] = "true"
    else:
        env["MAIL_ENABLED"] = "false"

    # --- system-level choices for the installer ---
    print("\n· System setup (applied by the installer):")
    do_harden = ask_bool("Harden the OS (auto-updates, firewall, fail2ban)?", True)
    do_zabbix = ask_bool("Install the Zabbix monitoring agent?", False)
    do_zabbix_server = False
    if do_zabbix and hw.enable_zabbix_server:
        print("  Your hardware can host a full Zabbix SERVER (not just the agent).")
        do_zabbix_server = ask_bool("Install a Zabbix server here too?", False)
    elif do_zabbix:
        print("  (This hardware should run the agent only — host the Zabbix server elsewhere.)")

    # --- write files ---
    _write_env(env)
    _write_choices(do_harden, do_zabbix, do_zabbix_server)
    print("\n✅ Wrote .env and .install-choices.")
    print("   Review/edit .env any time; per-server settings use the `set` command in Discord.")
    return 0


def _write_env(env: dict[str, str]) -> None:
    example = APP_DIR / ".env.example"
    target = APP_DIR / ".env"
    lines: list[str] = []
    written = set()
    # start from the example so every documented key is present + commented
    if example.exists():
        for raw in example.read_text().splitlines():
            stripped = raw.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0]
                if key in env:
                    lines.append(f"{key}={env[key]}")
                    written.add(key)
                    continue
            lines.append(raw)
    # append any keys not covered by the example
    extra = [k for k in env if k not in written]
    if extra:
        lines.append("\n# --- set by onboarding ---")
        lines += [f"{k}={env[k]}" for k in extra]
    target.write_text("\n".join(lines) + "\n")


def _write_choices(harden: bool, zabbix: bool, zabbix_server: bool = False) -> None:
    (APP_DIR / ".install-choices").write_text(
        f"HARDEN={1 if harden else 0}\n"
        f"ZABBIX={1 if zabbix else 0}\n"
        f"ZABBIX_SERVER={1 if zabbix_server else 0}\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
