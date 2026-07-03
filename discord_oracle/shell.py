"""The command-line simulation (mode two).

Two dialects share one filesystem: ``cmd`` (Windows Command Prompt) and
``powershell``. The difference is deliberate and educational — in ``cmd``,
``cp``/``ls``/``cat`` are *not* real commands and error exactly the way a real
box does; typing ``powershell`` drops you into a session where those aliases
resolve to Copy-Item/Get-ChildItem/Get-Content. Get a command wrong and you get
the real error, not a helpful guess. That is the point.

The interpreter mutates the player object in memory (cwd, dialect, privilege,
flags); the engine persists it after each line. Filesystem changes persist
immediately via the Store.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from datetime import datetime

from . import network
from .filesystem import FSError, VirtualFS, normalize
from .state import Node, Player, Store


@dataclass
class ShellResult:
    output: str
    signal: str | None = None  # e.g. "exit_to_desktop"


def _fmt_dt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%m/%d/%Y  %I:%M %p")


def _fmt_size(n: int) -> str:
    return f"{n:,}"


class Shell:
    def __init__(self, store: Store, fs: VirtualFS, player: Player) -> None:
        self.store = store
        self.fs = fs
        self.player = player

    # ---- entry point ---------------------------------------------------
    def run(self, line: str) -> ShellResult:
        line = line.rstrip("\n")
        if not line.strip():
            return ShellResult("")

        # Redirection: echo text > file  /  command >> file
        redirect: tuple[str, bool] | None = None
        for op, append in ((">>", True), (">", False)):
            if op in line:
                left, _, right = line.partition(op)
                target = right.strip().strip('"')
                if target:
                    line = left.strip()
                    redirect = (target, append)
                break

        try:
            tokens = shlex.split(line, posix=False)
        except ValueError:
            tokens = line.split()
        if not tokens:
            return ShellResult("")

        cmd = tokens[0].lower().strip('"')
        args = [t.strip('"') for t in tokens[1:]]

        table = self._table()
        handler = table.get(cmd)
        if handler is None:
            return ShellResult(self._not_recognized(tokens[0]))

        try:
            result = handler(args)
        except FSError as exc:
            return ShellResult(str(exc))

        if isinstance(result, ShellResult):
            out = result
        else:
            out = ShellResult(result)

        # Apply redirection to the produced text (echo/type/dir piped to a file).
        if redirect is not None and out.signal is None:
            target, append = redirect
            body = out.output
            if body and not body.endswith("\n"):
                body += "\n"
            try:
                self.fs.write_file(
                    target, self.player.cwd, body, self.player.privilege,
                    self.player.username, append=append,
                )
                return ShellResult("")
            except FSError as exc:
                return ShellResult(str(exc))
        return out

    # ---- dispatch tables ----------------------------------------------
    def _table(self) -> dict:
        common = {
            "cd": self.cmd_cd, "chdir": self.cmd_cd,
            "dir": self.cmd_dir,
            "type": self.cmd_type,
            "copy": self.cmd_copy,
            "move": self.cmd_move,
            "del": self.cmd_del, "erase": self.cmd_del,
            "md": self.cmd_mkdir, "mkdir": self.cmd_mkdir,
            "rd": self.cmd_rmdir, "rmdir": self.cmd_rmdir,
            "ren": self.cmd_ren, "rename": self.cmd_ren,
            "echo": self.cmd_echo,
            "cls": self.cmd_cls, "clear": self.cmd_cls,
            "tree": self.cmd_tree,
            "whoami": self.cmd_whoami,
            "hostname": self.cmd_hostname,
            "ver": self.cmd_ver,
            "systeminfo": self.cmd_systeminfo,
            "ipconfig": self.cmd_ipconfig,
            "ping": self.cmd_ping,
            "tracert": self.cmd_tracert, "traceroute": self.cmd_tracert,
            "nslookup": self.cmd_nslookup,
            "netstat": self.cmd_netstat,
            "arp": self.cmd_arp,
            "tasklist": self.cmd_tasklist,
            "net": self.cmd_net,
            "sc": self.cmd_sc,
            "reg": self.cmd_reg,
            "schtasks": self.cmd_schtasks,
            "findstr": self.cmd_findstr,
            "set": self.cmd_set,
            "runas": self.cmd_runas,
            "help": self.cmd_help,
            "exit": self.cmd_exit,
            "powershell": self.cmd_powershell, "pwsh": self.cmd_powershell,
        }
        if self.player.dialect == "powershell":
            common.update({
                "ls": self.cmd_dir, "gci": self.cmd_dir,
                "get-childitem": self.cmd_dir,
                "cat": self.cmd_type, "gc": self.cmd_type,
                "get-content": self.cmd_type,
                "cp": self.cmd_copy, "copy-item": self.cmd_copy, "cpi": self.cmd_copy,
                "mv": self.cmd_move, "move-item": self.cmd_move, "mi": self.cmd_move,
                "rm": self.cmd_del, "del": self.cmd_del, "remove-item": self.cmd_del,
                "ri": self.cmd_del,
                "pwd": self.cmd_pwd, "gl": self.cmd_pwd, "get-location": self.cmd_pwd,
                "sl": self.cmd_cd, "set-location": self.cmd_cd,
                "ni": self.cmd_mkdir, "new-item": self.cmd_mkdir,
                "write-output": self.cmd_echo, "write-host": self.cmd_echo,
                "select-string": self.cmd_findstr, "sls": self.cmd_findstr,
                "test-path": self.cmd_testpath,
            })
        return common

    def _not_recognized(self, name: str) -> str:
        if self.player.dialect == "powershell":
            return (
                f"{name} : The term '{name}' is not recognized as the name of a "
                "cmdlet, function, script file, or operable program. Check the "
                "spelling of the name, or if a path was included, verify that the "
                "path is correct and try again."
            )
        return (
            f"'{name}' is not recognized as an internal or external command,\n"
            "operable program or batch file."
        )

    # ---- navigation ----------------------------------------------------
    def cmd_cd(self, args: list[str]) -> str:
        if not args:
            return self.player.cwd
        target = args[-1]
        if target in ("\\", "/"):
            self.player.cwd = "C:\\"
            return ""
        rp = self.fs.resolve(target, self.player.cwd)
        if rp.node is None or rp.node.kind != "dir":
            return "The system cannot find the path specified."
        self.player.cwd = self.fs.path_of(rp.node)
        return ""

    def cmd_pwd(self, args: list[str]) -> str:
        if self.player.dialect == "powershell":
            return f"\nPath\n----\n{self.player.cwd}"
        return self.player.cwd

    # ---- listing -------------------------------------------------------
    def cmd_dir(self, args: list[str]) -> str:
        path = next((a for a in args if not a.startswith("/") and not a.startswith("-")), ".")
        try:
            abspath, children = self.fs.list_dir(path, self.player.cwd)
        except FSError as exc:
            return str(exc)
        if self.player.dialect == "powershell" and args and args[0].lower() in (
            "ls", "gci", "get-childitem"
        ):
            pass
        visible = [c for c in children if not c.hidden or "/a" in [a.lower() for a in args]]
        return self._dir_cmd_format(abspath, visible)

    def _dir_cmd_format(self, abspath: str, children: list[Node]) -> str:
        lines = [
            " Volume in drive C has no label.",
            " Volume Serial Number is 7A3F-1D2E",
            "",
            f" Directory of {abspath}",
            "",
        ]
        file_count = 0
        dir_count = 0
        total_bytes = 0
        # Fabricate . and .. for non-root dirs.
        rp = self.fs.resolve(abspath, self.player.cwd)
        if rp.node and rp.node.parent_id is not None:
            ts = _fmt_dt(rp.node.modified_at)
            lines.append(f"{ts}    <DIR>          .")
            lines.append(f"{ts}    <DIR>          ..")
            dir_count += 2
        for c in children:
            ts = _fmt_dt(c.modified_at)
            if c.kind == "dir":
                lines.append(f"{ts}    <DIR>          {c.name}")
                dir_count += 1
            else:
                size = len(c.content.encode("utf-8", "replace"))
                total_bytes += size
                file_count += 1
                lines.append(f"{ts}    {_fmt_size(size):>14} {c.name}")
        lines.append(
            f"{file_count:>16} File(s) {_fmt_size(total_bytes):>15} bytes"
        )
        lines.append(
            f"{dir_count:>16} Dir(s)  53,209,780,224 bytes free"
        )
        return "\n".join(lines)

    def cmd_tree(self, args: list[str]) -> str:
        path = args[0] if args and not args[0].startswith("/") else "."
        rp = self.fs.resolve(path, self.player.cwd)
        if rp.node is None or rp.node.kind != "dir":
            return "Invalid path"
        show_files = any(a.lower() == "/f" for a in args)
        lines = [self.fs.path_of(rp.node), ""]
        self._tree_walk(rp.node, "", lines, show_files)
        return "\n".join(lines)

    def _tree_walk(self, node: Node, prefix: str, lines: list[str], files: bool) -> None:
        children = self.store.list_children(self.player.player_key, node.id)
        dirs = [c for c in children if c.kind == "dir"]
        entries = children if files else dirs
        for i, c in enumerate(entries):
            last = i == len(entries) - 1
            branch = "└───" if last else "├───"
            lines.append(prefix + branch + c.name)
            if c.kind == "dir":
                self._tree_walk(c, prefix + ("    " if last else "│   "), lines, files)

    # ---- file content --------------------------------------------------
    def cmd_type(self, args: list[str]) -> str:
        if not args:
            return "The syntax of the command is incorrect."
        target = args[-1]
        try:
            content = self.fs.read_file(target, self.player.cwd)
        except FSError as exc:
            return str(exc)
        return content if content else ""

    def cmd_testpath(self, args: list[str]) -> str:
        if not args:
            return "False"
        return "True" if self.fs.exists(args[-1], self.player.cwd) else "False"

    # ---- mutations -----------------------------------------------------
    def cmd_copy(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("/") and not a.startswith("-")]
        if len(pos) < 2:
            return "The syntax of the command is incorrect."
        return self.fs.copy(
            pos[0], pos[-1], self.player.cwd, self.player.privilege, self.player.username
        )

    def cmd_move(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("/") and not a.startswith("-")]
        if len(pos) < 2:
            return "The syntax of the command is incorrect."
        self.fs.move(pos[0], pos[-1], self.player.cwd, self.player.privilege)
        return "        1 file(s) moved."

    def cmd_del(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("/") and not a.startswith("-")]
        if not pos:
            return "The syntax of the command is incorrect."
        errs = []
        for target in pos:
            try:
                if self.fs.is_dir(target, self.player.cwd):
                    # del on a directory in cmd removes its files; keep it simple.
                    self.fs.remove_dir(target, self.player.cwd, self.player.privilege)
                else:
                    self.fs.remove_file(target, self.player.cwd, self.player.privilege)
            except FSError as exc:
                errs.append(str(exc))
        return "\n".join(errs)

    def cmd_mkdir(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("/") and not a.startswith("-")
               and a.lower() not in ("-itemtype", "directory", "-path", "-name")]
        if not pos:
            return "The syntax of the command is incorrect."
        for target in pos:
            self.fs.make_dir(target, self.player.cwd, self.player.privilege, self.player.username)
        return ""

    def cmd_rmdir(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("/") and not a.startswith("-")]
        recurse = any(a.lower() in ("/s", "-recurse") for a in args)
        if not pos:
            return "The syntax of the command is incorrect."
        target = pos[0]
        if recurse:
            rp = self.fs.resolve(target, self.player.cwd)
            if rp.node and rp.node.kind == "dir":
                if rp.parent and rp.parent.protected and self.player.privilege == "user":
                    return "Access is denied."
                self.store.delete_node(rp.node.id)
                return ""
            return "The system cannot find the file specified."
        self.fs.remove_dir(target, self.player.cwd, self.player.privilege)
        return ""

    def cmd_ren(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("/")]
        if len(pos) < 2:
            return "The syntax of the command is incorrect."
        self.fs.rename(pos[0], pos[1], self.player.cwd, self.player.privilege)
        return ""

    def cmd_echo(self, args: list[str]) -> str:
        if not args:
            return "ECHO is on."
        text = " ".join(args)
        if text.lower() == "off" or text.lower() == "on":
            return ""
        return text

    def cmd_cls(self, args: list[str]) -> str:
        return "\x00CLS"  # engine interprets as "clear scrollback" hint; renders blank

    # ---- identity / system --------------------------------------------
    def cmd_whoami(self, args: list[str]) -> str:
        if args and args[0].lower() in ("/priv", "-priv"):
            lvl = self.player.privilege
            enabled = "Enabled" if lvl in ("admin", "system") else "Disabled"
            return (
                "\nPRIVILEGES INFORMATION\n----------------------\n\n"
                "Privilege Name                Description                          State\n"
                "============================= ==================================== ========\n"
                f"SeDebugPrivilege              Debug programs                       {enabled}\n"
                f"SeImpersonatePrivilege        Impersonate a client after auth      {enabled}\n"
            )
        domain = "meridian"
        if self.player.privilege == "system":
            return "nt authority\\system"
        return f"{domain}\\{self.player.username}"

    def cmd_hostname(self, args: list[str]) -> str:
        return "MERIDIAN-DC01"

    def cmd_ver(self, args: list[str]) -> str:
        return "\nMicrosoft Windows [Version 10.0.17763.5458]"

    def cmd_systeminfo(self, args: list[str]) -> str:
        return (
            "\nHost Name:                 MERIDIAN-DC01\n"
            "OS Name:                   Microsoft Windows Server 2019 Datacenter\n"
            "OS Version:                10.0.17763 N/A Build 17763\n"
            "OS Manufacturer:           Microsoft Corporation\n"
            "Registered Owner:          Meridian Logistics\n"
            "Product ID:                00429-00521-62775-AA483\n"
            "Original Install Date:     3/14/2021, 8:02:11 AM\n"
            "System Boot Time:          7/1/2026, 2:41:55 AM\n"
            "System Manufacturer:       VMware, Inc.\n"
            "System Model:              VMware7,1\n"
            "Domain:                    meridian.local\n"
            "Total Physical Memory:     16,384 MB\n"
            "Hotfix(s):                 4 Hotfix(s) Installed.\n"
        )

    def cmd_ipconfig(self, args: list[str]) -> str:
        return network.ipconfig()

    def cmd_ping(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("-") and not a.startswith("/")]
        if not pos:
            return "Usage: ping [-t] [-n count] target_name"
        return network.ping(pos[-1])

    def cmd_tracert(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("-") and not a.startswith("/")]
        if not pos:
            return "Usage: tracert target_name"
        return network.tracert(pos[-1])

    def cmd_nslookup(self, args: list[str]) -> str:
        if not args:
            return network.nslookup("dc01")
        return network.nslookup(args[-1])

    def cmd_netstat(self, args: list[str]) -> str:
        return network.netstat()

    def cmd_arp(self, args: list[str]) -> str:
        return network.arp()

    # ---- IR-flavored canned tools -------------------------------------
    def cmd_tasklist(self, args: list[str]) -> str:
        return (
            "\nImage Name                     PID Session Name        Session#    Mem Usage\n"
            "========================= ======== ================ =========== ============\n"
            "System                           4 Services                   0        140 K\n"
            "lsass.exe                      612 Services                   0     14,208 K\n"
            "services.exe                   604 Services                   0      9,880 K\n"
            "svchost.exe                    916 Services                   0     52,004 K\n"
            "explorer.exe                  4120 RDP-Tcp#3                  3     78,332 K\n"
            "cmd.exe                       5044 RDP-Tcp#3                  3      3,116 K\n"
            "update.exe                    6612 Services                   0     41,880 K\n"
            "powershell.exe                6740 Services                   0     96,540 K\n"
        )

    def cmd_net(self, args: list[str]) -> str:
        sub = args[0].lower() if args else ""
        if sub == "user" and len(args) == 1:
            return (
                "\nUser accounts for \\\\MERIDIAN-DC01\n\n"
                "-------------------------------------------------------------------------------\n"
                "Administrator            DefaultAccount           Guest\n"
                "jmartin                  krbtgt                   svc_backup\n"
                "svc_sql                  helpdesk                 dwhitfield\n"
                "The command completed successfully.\n"
            )
        if sub == "user" and len(args) >= 2:
            u = args[1]
            if u.lower() == "jmartin":
                return (
                    f"\nUser name                    jmartin\n"
                    "Full Name                    Jordan Martin\n"
                    "Account active               Yes\n"
                    "Password last set            6/30/2026 11:52:14 PM\n"
                    "Local Group Memberships      *Users\n"
                    "Global Group memberships     *Domain Users\n"
                    "The command completed successfully.\n"
                )
            if u.lower() == "svc_backup":
                return (
                    "\nUser name                    svc_backup\n"
                    "Account active               Yes\n"
                    "Password last set            7/1/2026 3:12:40 AM\n"
                    "Local Group Memberships      *Administrators   *Backup Operators\n"
                    "Global Group memberships     *Domain Admins\n"
                    "The command completed successfully.\n"
                )
            return "The user name could not be found.\n"
        if sub in ("localgroup", "group") and len(args) >= 2 and \
                args[1].lower() == "administrators":
            return (
                "\nAlias name     administrators\n"
                "Members\n"
                "-------------------------------------------------------------------------------\n"
                "Administrator\nDomain Admins\nsvc_backup\n"
                "The command completed successfully.\n"
            )
        return "The syntax of this command is:\n\nNET USER | NET LOCALGROUP | ..."

    def cmd_sc(self, args: list[str]) -> str:
        if args and args[0].lower() == "query":
            return (
                "\nSERVICE_NAME: WinDefendUpdate\n"
                "        TYPE               : 10  WIN32_OWN_PROCESS\n"
                "        STATE              : 4  RUNNING\n"
                "        BINARY_PATH_NAME   : C:\\Users\\jmartin\\AppData\\Roaming\\update.exe\n"
            )
        return "[SC] Usage: sc query [service name]"

    def cmd_schtasks(self, args: list[str]) -> str:
        return (
            "\nFolder: \\\nTaskName                                 Next Run Time          Status\n"
            "======================================== ====================== ===============\n"
            "\\Microsoft\\Windows\\SystemUpdate          7/3/2026 4:00:00 AM    Ready\n"
            "  -> C:\\ProgramData\\svc\\beacon.ps1\n"
        )

    def cmd_reg(self, args: list[str]) -> str:
        if args and args[0].lower() == "query":
            key = args[1] if len(args) > 1 else ""
            if "run" in key.lower():
                return (
                    f"\n{key}\n"
                    "    SecurityHealth    REG_EXPAND_SZ    %windir%\\system32\\SecurityHealth.exe\n"
                    "    OneDriveSetup     REG_SZ           C:\\Windows\\SysWOW64\\OneDriveSetup.exe\n"
                    "    WinUpdate         REG_SZ           C:\\Users\\jmartin\\AppData\\Roaming\\update.exe\n"
                )
            return f"\n{key}\n    (Default)    REG_SZ    (value not set)\n"
        return "ERROR: Invalid syntax."

    def cmd_findstr(self, args: list[str]) -> str:
        pos = [a for a in args if not a.startswith("/") and not a.startswith("-")]
        if len(pos) < 2:
            return "FINDSTR: Bad command line"
        pattern = pos[0].strip('"')
        matches = []
        for target in pos[1:]:
            try:
                content = self.fs.read_file(target, self.player.cwd)
            except FSError:
                continue
            for ln in content.splitlines():
                if pattern.lower() in ln.lower():
                    matches.append(ln)
        return "\n".join(matches)

    def cmd_set(self, args: list[str]) -> str:
        if not args:
            return (
                "COMPUTERNAME=MERIDIAN-DC01\n"
                f"USERNAME={self.player.username}\n"
                "USERDOMAIN=MERIDIAN\n"
                "USERPROFILE=C:\\Users\\jmartin\n"
                "SystemRoot=C:\\Windows\n"
                "TEMP=C:\\Users\\jmartin\\AppData\\Local\\Temp\n"
            )
        return ""

    def cmd_runas(self, args: list[str]) -> str:
        """Privilege escalation. Only works once the player has discovered the
        svc_backup credentials (a Domain Admin service account) planted in a file
        — a real, learnable finding rather than a cheat code."""
        joined = " ".join(args).lower()
        if "svc_backup" in joined:
            if self.player.flags.get("found_creds"):
                self.player.privilege = "admin"
                return (
                    "Attempting to start as user \"meridian\\svc_backup\" ...\n"
                    "Session elevated. You are now operating with Domain Admin rights.\n"
                    "(Protected paths such as C:\\Windows\\System32 are now writable.)"
                )
            return (
                "RUNAS ERROR: Unable to run - the specified logon session does not "
                "exist. You need valid credentials for svc_backup first — find them."
            )
        return "RUNAS USAGE: runas /user:<domain>\\<user> \"command\""

    # ---- mode / help ---------------------------------------------------
    def cmd_powershell(self, args: list[str]) -> str:
        if args:  # `powershell -c "..."` one-liner: just run it in ps context
            self.player.dialect = "powershell"
            sub = " ".join(a for a in args if not a.startswith("-"))
            if sub:
                return Shell(self.store, self.fs, self.player).run(sub).output
        self.player.dialect = "powershell"
        return (
            "Windows PowerShell\nCopyright (C) Microsoft Corporation. All rights reserved.\n"
            "\n(Now in PowerShell. Aliases like ls/cat/cp/rm work here. Type 'exit' "
            "to return to cmd.)"
        )

    def cmd_help(self, args: list[str]) -> str:
        return (
            "Available commands (this is a Windows box — try what you'd really type):\n"
            "  Navigation : cd, dir, tree, type, pwd\n"
            "  Files      : copy, move, del, ren, mkdir, rmdir, echo > file\n"
            "  System     : whoami [/priv], hostname, systeminfo, ver, tasklist, set\n"
            "  Network    : ipconfig, ping, tracert, nslookup, netstat, arp\n"
            "  Recon      : net user, net localgroup, sc query, reg query, schtasks, findstr\n"
            "  Elevate    : runas /user:meridian\\svc_backup (needs creds you must find)\n"
            "  Shells     : powershell  (switch dialect),  exit  (leave the terminal)\n"
        )

    def cmd_exit(self, args: list[str]) -> ShellResult:
        if self.player.dialect == "powershell":
            self.player.dialect = "cmd"
            return ShellResult("")  # exit powershell back to cmd
        return ShellResult("", signal="exit_to_desktop")
