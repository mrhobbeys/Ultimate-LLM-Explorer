import pytest

from discord_oracle.engine import Engine
from discord_oracle.llm import LLM


@pytest.fixture()
def engine(store):
    return Engine(store, LLM())  # LLM auto-selects 'none' in tests


@pytest.fixture()
def key(engine, store):
    k = "dm:eng"
    engine.ensure_player(k, None, "eng")
    return k


async def test_login_flow(engine, key):
    # Fresh player starts at the login screen.
    resp = engine.opening_scene(engine.store.get_player(key))
    assert "login" in " ".join(resp.options).lower()
    resp = await engine.handle(key, "login")
    assert "Desktop" in (resp.title or "")


async def test_open_terminal_switches_to_shell(engine, key):
    await engine.handle(key, "login")
    resp = await engine.handle(key, "terminal")
    assert resp.kind == "shell"
    assert engine.store.get_player(key).mode == "shell"
    # opened_terminal objective should have fired.
    assert engine.store.get_player(key).flags.get("opened_terminal")


async def test_shell_progress_flags_and_xp(engine, key):
    await engine.handle(key, "login")
    await engine.handle(key, "terminal")
    # netstat -> beacon + exfil objectives.
    resp = await engine.handle(key, "netstat")
    flags = engine.store.get_player(key).flags
    assert flags.get("found_beacon")
    assert flags.get("found_exfil")
    assert flags.get("xp", 0) > 0


async def test_exit_returns_to_desktop(engine, key):
    await engine.handle(key, "login")
    await engine.handle(key, "terminal")
    resp = await engine.handle(key, "exit")
    assert resp.kind == "scene"
    assert engine.store.get_player(key).mode == "adventure"


async def test_reading_creds_enables_escalation(engine, key):
    await engine.handle(key, "login")
    await engine.handle(key, "terminal")
    await engine.handle(key, "type C:\\ProgramData\\svc\\config.ini")
    assert engine.store.get_player(key).flags.get("found_creds")
    resp = await engine.handle(key, "runas /user:meridian\\svc_backup cmd")
    assert engine.store.get_player(key).privilege == "admin"
    assert engine.store.get_player(key).flags.get("escalated")


async def test_conversation_sets_milestone(engine, key):
    await engine.handle(key, "login")
    await engine.handle(key, "chat")
    resp = await engine.handle(key, "talk raj")
    assert "Raj" in (resp.title or "")
    assert engine.store.get_player(key).flags.get("met_raj")
    # Rule-based reply works with no LLM.
    reply = await engine.handle(key, "where should I look for persistence?")
    assert reply.body


async def test_full_case_to_report(engine, key):
    await engine.handle(key, "login")
    await engine.handle(key, "terminal")
    for cmd in [
        "tasklist", "netstat", 'reg query "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"',
        "schtasks", "type C:\\inetpub\\wwwroot\\uploads\\shell.aspx",
        "type C:\\ProgramData\\svc\\config.ini",
    ]:
        await engine.handle(key, cmd)
    await engine.handle(key, "exit")
    await engine.handle(key, "chat")
    await engine.handle(key, "talk karen")
    await engine.handle(key, "back")
    await engine.handle(key, "report")
    await engine.handle(key, "submit")
    flags = engine.store.get_player(key).flags
    assert flags.get("wrote_report")
    # Should have ranked up past Tier-1 by now.
    assert flags.get("level", 1) >= 2
