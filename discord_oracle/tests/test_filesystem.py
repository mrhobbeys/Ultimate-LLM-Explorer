import pytest

from discord_oracle.filesystem import FSError, VirtualFS, normalize


def test_normalize_variants():
    cwd = "C:\\Users\\jmartin"
    assert normalize(".", cwd) == cwd
    assert normalize("..", cwd) == "C:\\Users"
    assert normalize("Desktop", cwd) == "C:\\Users\\jmartin\\Desktop"
    assert normalize("C:/Windows/System32", cwd) == "C:\\Windows\\System32"
    assert normalize("\\Temp", cwd) == "C:\\Temp"
    assert normalize("..\\..\\..", cwd) == "C:\\"  # can't go above root


def test_case_insensitive_resolution(store, player):
    fs = VirtualFS(store, player.player_key)
    # NTFS is case-insensitive: CMd.exe resolves to cmd.exe.
    rp = fs.resolve("c:/WINDOWS/system32/CMd.exe", player.cwd)
    assert rp.node is not None
    assert rp.node.name == "cmd.exe"


def test_move_persists(store, player):
    fs = VirtualFS(store, player.player_key)
    fs.write_file("C:\\Temp\\a.txt", player.cwd, "hello", "user", "jmartin")
    fs.move("C:\\Temp\\a.txt", "C:\\Temp\\b.txt", player.cwd, "user")
    assert not fs.exists("C:\\Temp\\a.txt", player.cwd)
    assert fs.read_file("C:\\Temp\\b.txt", player.cwd) == "hello"


def test_copy_then_independent_edit(store, player):
    fs = VirtualFS(store, player.player_key)
    fs.write_file("C:\\Temp\\src.txt", player.cwd, "one", "user", "jmartin")
    fs.copy("C:\\Temp\\src.txt", "C:\\Temp\\dst.txt", player.cwd, "user", "jmartin")
    fs.write_file("C:\\Temp\\dst.txt", player.cwd, "two", "user", "jmartin")
    assert fs.read_file("C:\\Temp\\src.txt", player.cwd) == "one"
    assert fs.read_file("C:\\Temp\\dst.txt", player.cwd) == "two"


def test_protected_write_denied_for_user(store, player):
    fs = VirtualFS(store, player.player_key)
    # The classic "cp utilman.exe cmd.exe" in System32 as a normal user -> denied.
    with pytest.raises(FSError) as exc:
        fs.copy(
            "C:\\Windows\\System32\\utilman.exe",
            "C:\\Windows\\System32\\cmd.exe",
            player.cwd, "user", "jmartin",
        )
    assert "Access is denied." in str(exc.value)


def test_protected_write_allowed_for_admin(store, player):
    fs = VirtualFS(store, player.player_key)
    # After escalation the same op succeeds (utilman/cmd swap persistence).
    result = fs.copy(
        "C:\\Windows\\System32\\utilman.exe",
        "C:\\Windows\\System32\\evilcmd.exe",
        player.cwd, "admin", "svc_backup",
    )
    assert "copied" in result
    assert fs.exists("C:\\Windows\\System32\\evilcmd.exe", player.cwd)


def test_read_missing_file(store, player):
    fs = VirtualFS(store, player.player_key)
    with pytest.raises(FSError) as exc:
        fs.read_file("C:\\Temp\\nope.txt", player.cwd)
    assert "cannot find the file" in str(exc.value)
