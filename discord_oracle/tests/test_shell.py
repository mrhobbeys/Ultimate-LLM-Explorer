from discord_oracle.filesystem import VirtualFS
from discord_oracle.shell import Shell


def sh(store, player):
    return Shell(store, VirtualFS(store, player.player_key), player)


def test_cmd_does_not_recognize_unix_cp(store, player):
    # The user's exact scenario: they typed a unix command in cmd.exe.
    result = sh(store, player).run("cp utilman.exe CMd.exe")
    assert "'cp' is not recognized as an internal or external command" in result.output


def test_powershell_enables_aliases(store, player):
    shell = sh(store, player)
    shell.run("powershell")
    assert player.dialect == "powershell"
    # In PS, cp is a real alias — now the missing-source error is the FS one.
    result = shell.run("cp doesnotexist.txt out.txt")
    assert "cannot find the file" in result.output.lower()


def test_cd_and_dir(store, player):
    shell = sh(store, player)
    assert shell.run("cd C:\\Temp").output == ""
    assert player.cwd == "C:\\Temp"
    listing = shell.run("dir").output
    assert "svc_host.ps1" in listing
    assert "Directory of C:\\Temp" in listing


def test_type_reads_incident_ticket(store, player):
    shell = sh(store, player)
    out = shell.run("type C:\\Users\\jmartin\\Desktop\\readme_incident.txt").output
    assert "INCIDENT #IR-2026-0714" in out


def test_echo_redirect_creates_file(store, player):
    shell = sh(store, player)
    shell.run('echo hello world > C:\\Temp\\note.txt')
    out = shell.run("type C:\\Temp\\note.txt").output
    assert "hello world" in out


def test_move_via_shell_persists(store, player):
    shell = sh(store, player)
    shell.run('echo data > C:\\Temp\\x.txt')
    shell.run("move C:\\Temp\\x.txt C:\\Temp\\y.txt")
    assert "cannot find" in shell.run("type C:\\Temp\\x.txt").output.lower()
    assert "data" in shell.run("type C:\\Temp\\y.txt").output


def test_system32_copy_denied_then_allowed(store, player):
    shell = sh(store, player)
    shell.run("cd C:\\Windows\\System32")
    denied = shell.run("copy utilman.exe cmd2.exe")
    assert "Access is denied." in denied.output
    # Simulate escalation.
    player.privilege = "admin"
    ok = shell.run("copy utilman.exe cmd2.exe")
    assert "copied" in ok.output


def test_runas_requires_found_creds(store, player):
    shell = sh(store, player)
    denied = shell.run("runas /user:meridian\\svc_backup cmd")
    assert "find them" in denied.output.lower() or "does not exist" in denied.output.lower()
    player.flags["found_creds"] = True
    ok = shell.run("runas /user:meridian\\svc_backup cmd")
    assert player.privilege == "admin"
    assert "Domain Admin" in ok.output


def test_ping_internal_and_external(store, player):
    shell = sh(store, player)
    assert "Reply from 10.20.5.11" in shell.run("ping dc02").output
    ext = shell.run("tracert 185.220.101.44").output
    assert "unreachable" in ext.lower()


def test_exit_signals_desktop(store, player):
    shell = sh(store, player)
    assert shell.run("exit").signal == "exit_to_desktop"


def test_powershell_exit_returns_to_cmd(store, player):
    shell = sh(store, player)
    shell.run("powershell")
    res = shell.run("exit")
    assert res.signal is None
    assert player.dialect == "cmd"
