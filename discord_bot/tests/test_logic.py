"""Unit tests for the dependency-free logic (no Discord connection needed)."""

from __future__ import annotations

import time

from bot.analysis import TextAnalyzer, normalize_leet
from bot.cogs.ranking import level_for_xp, xp_for_level
from bot.cogs.search import build_query
from bot.llm import LLMClient, _LRU, Verdict
from bot.presets import PRESETS, resolve
from bot.ratelimit import DuplicateTracker, SlidingWindow


# --- analysis --------------------------------------------------------------- #
def test_normalize_leet_folds_obfuscation():
    assert normalize_leet("f.u.c.k") == "fuck"
    assert normalize_leet("F U C K") == "fuck"
    assert normalize_leet("$hit") == "shit"


def test_profanity_detection_and_obfuscation():
    a = TextAnalyzer()
    assert a.find_profanity("you are a piece of sh1t")  # leet
    assert a.find_profanity("f u c k this")
    assert not a.find_profanity("what a lovely day")


def test_clean_message_low_suspicion():
    a = TextAnalyzer()
    assert a.analyze("hey how is everyone doing today").suspicion < 0.25


def test_shouting_and_symbol_soup_raise_suspicion():
    a = TextAnalyzer()
    assert a.analyze("AAAAAAAAAAAAAAAA GET OUT NOW").suspicion > 0


def test_custom_wordlist(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("frobnicate\n# comment\nquux\n")
    a = TextAnalyzer(wordlist_path=str(wl))
    assert "frobnicate" in a.profanity
    assert a.find_profanity("please do not frobnicate here")


# --- ratelimit -------------------------------------------------------------- #
def test_sliding_window_trips_over_limit():
    w = SlidingWindow(limit=3, window=10)
    now = 1000.0
    results = [w.over_limit(1, now + i * 0.1) for i in range(5)]
    assert results == [False, False, False, True, True]


def test_sliding_window_expires():
    w = SlidingWindow(limit=2, window=5)
    w.hit(1, 100.0)
    w.hit(1, 101.0)
    assert not w.over_limit(1, 200.0)  # old events aged out


def test_duplicate_tracker():
    d = DuplicateTracker(limit=3, window=30)
    now = 500.0
    assert not d.over_limit(1, "same", now)
    assert not d.over_limit(1, "same", now + 1)
    assert d.over_limit(1, "same", now + 2)


# --- ranking ---------------------------------------------------------------- #
def test_level_curve_monotonic():
    base, exp = 50, 1.6
    assert level_for_xp(0, base, exp) == 0
    prev = -1
    for xp in range(0, 5000, 137):
        lvl = level_for_xp(xp, base, exp)
        assert lvl >= prev
        prev = lvl


def test_xp_for_level_roundtrip():
    base, exp = 50, 1.6
    lvl = 6
    needed = xp_for_level(lvl, base, exp)
    assert level_for_xp(needed, base, exp) >= lvl


# --- search builder --------------------------------------------------------- #
def test_search_query_builder_passthrough():
    q, warnings = build_query(
        None, None, "from:bob in:general has:link before:2024-01-01 hello world".split()
    )
    assert "from:bob" in q and "in:general" in q and "has:link" in q
    assert "before:2024-01-01" in q and "hello world" in q
    assert not warnings


def test_search_query_builder_warns_on_bad_values():
    q, warnings = build_query(None, None, ["has:banana", "before:nope"])
    assert warnings  # both invalid


# --- llm parsing ------------------------------------------------------------ #
def test_llm_parse_plain_json():
    v = LLMClient._parse('{"category":"harassment","severity":0.9,"reason":"insult"}')
    assert v.ok and v.category == "harassment" and v.is_harmful


def test_llm_parse_code_fence():
    v = LLMClient._parse('```json\n{"category":"ok","severity":0.0,"reason":"fine"}\n```')
    assert v.ok and not v.is_harmful


def test_llm_parse_garbage():
    assert not LLMClient._parse("i cannot help with that").ok


def test_llm_lru_evicts():
    lru = _LRU(2)
    lru.put("a", Verdict())
    lru.put("b", Verdict())
    lru.put("c", Verdict())
    assert lru.get("a") is None  # evicted
    assert lru.get("c") is not None


# --- presets ---------------------------------------------------------------- #
def test_presets_resolve_by_key_and_name():
    assert resolve("family").key == "family"
    assert resolve("Gamer Lounge").key == "gamer"
    assert resolve("nonsense") is None


def test_preset_settings_are_complete():
    for p in PRESETS.values():
        s = p.settings()
        assert s["mod.mode"] in {"off", "shadow", "approve", "armed"}
        assert "mod.suspicion_low" in s and "mod.suspicion_high" in s
        assert float(s["mod.suspicion_low"]) <= float(s["mod.suspicion_high"])
