"""Mode one: the GUI / desktop layer.

This models the machine as screens you navigate by picking options — the login
screen, the desktop, the apps (email, chat, browser, tickets, report). Every
screen tells you where you are and offers a clear list of options to type.
Opening the Command Prompt hands off to mode two (the shell); typing ``exit``
in the shell brings you back to the desktop. One continuous world.

Screens are pure presentation + option routing; the engine owns state changes
(mode switches, flags, progression) so this module stays declarative.
"""

from __future__ import annotations

from dataclasses import dataclass

from .world import NPCS


@dataclass
class Scene:
    title: str
    body: str
    options: list[str]


def login_screen() -> Scene:
    return Scene(
        title="🖥️  MERIDIAN-DC01 — Windows Server 2019",
        body=(
            "You're at the console of the compromised domain controller. The lock "
            "screen shows the time and a single locked session: **meridian\\jmartin**.\n\n"
            "Your IR credentials are already provisioned. The incident ticket is "
            "waiting on the desktop."
        ),
        options=["`login` — sign in and reach the desktop"],
    )


def desktop_screen(flags: dict) -> Scene:
    unread = "  •  📧 1 unread from Dana (CISO)" if not flags.get("met_dana") else ""
    return Scene(
        title="🪟  Desktop — meridian\\jmartin",
        body=(
            "You're on the Windows desktop. The taskbar has Outlook, Teams, Edge, "
            "the ticket system, and a Command Prompt shortcut." + unread
        ),
        options=[
            "`terminal` — open the Command Prompt (drops into the live shell)",
            "`ticket` — open the incident ticket (your assignment)",
            "`email` — open Outlook",
            "`chat` — open Teams (talk to the team)",
            "`browser` — open Edge (the intranet)",
            "`report` — open your findings report",
            "`status` — your rank, XP, and objectives",
            "`logoff` — return to the lock screen",
        ],
    )


def people_screen(kind: str) -> Scene:
    app = "Outlook" if kind == "email" else "Teams"
    lines = [f"You open {app}. People you can reach:"]
    opts = []
    for npc in NPCS.values():
        lines.append(f"  • {npc.name} — {npc.title}")
        opts.append(f"`talk {npc.id}` — message {npc.name.split()[0]}")
    opts.append("`back` — return to the desktop")
    return Scene(
        title=f"{'📧' if kind == 'email' else '💬'}  {app}",
        body="\n".join(lines) + "\n\nOnce you're talking to someone, just type your message. `back` ends the conversation.",
        options=opts,
    )


def in_conversation_scene(npc_name: str) -> list[str]:
    return [
        "Type anything to say it.",
        "`back` — end the conversation and return to the desktop",
    ]


def browser_screen() -> Scene:
    return Scene(
        title="🌐  Edge — Meridian Intranet",
        body=(
            "The intranet home page loads from web01 (10.20.5.40). There's a file "
            "'uploads' area on the site — the same server the EDR flagged. You could "
            "confirm what's there from the terminal.\n\n"
            "Outbound internet is blocked by the perimeter firewall (you'll see it "
            "if you try tracert to anything external)."
        ),
        options=["`back` — return to the desktop"],
    )


def ticket_screen() -> Scene:
    return Scene(
        title="🎫  Incident Ticket IR-2026-0714",
        body=(
            "The full ticket is also on the desktop as readme_incident.txt. Summary:\n"
            "• EDR flagged PowerShell + outbound to 185.220.101.44 from this DC.\n"
            "• Suspected initial access via Karen Osei's workstation (a bad invoice).\n"
            "• Your tasks: confirm the intrusion, find persistence, find any webshell,\n"
            "  identify abused accounts, and write up findings.\n\n"
            "Open the terminal to start the investigation."
        ),
        options=["`terminal` — open the Command Prompt", "`back` — return to the desktop"],
    )


def report_screen(flags: dict) -> Scene:
    done = flags.get("objectives", {})
    findings = []
    if done.get("beacon"):
        findings.append("• Confirmed C2 beacon (update.exe / connection to 185.220.101.44).")
    if done.get("runkey"):
        findings.append("• Run-key persistence: WinUpdate -> AppData\\Roaming\\update.exe.")
    if done.get("schtask"):
        findings.append("• Scheduled task 'SystemUpdate' -> C:\\ProgramData\\svc\\beacon.ps1.")
    if done.get("webshell"):
        findings.append("• IIS webshell at inetpub\\wwwroot\\uploads\\shell.aspx (POSTs in logs).")
    if done.get("creds"):
        findings.append("• Staged Domain-Admin creds for svc_backup in ProgramData\\svc\\config.ini.")
    if done.get("exfil"):
        findings.append("• Exfil: staged 7z in C:\\Temp\\staging, outbound to 185.220.101.44.")
    body = "Your draft report compiles the objectives you've confirmed so far:\n\n"
    body += ("\n".join(findings) if findings else "(No findings confirmed yet — investigate in the terminal first.)")
    return Scene(
        title="📄  Findings Report — IR-2026-0714",
        body=body,
        options=[
            "`submit` — send the report to Dana (CISO)",
            "`back` — return to the desktop",
        ],
    )
