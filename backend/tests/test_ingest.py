from app.analyze.stats import rebuild_daily, summary
from app.ingest.service import ingest_path


def test_ingest_chatgpt_persists(tmp_db, fixtures_dir):
    results = ingest_path(tmp_db, fixtures_dir / "chatgpt_sample.json")
    assert any(r.provider == "chatgpt" for r in results)
    (c,) = tmp_db.execute("SELECT COUNT(*) FROM conversations").fetchone()
    (m,) = tmp_db.execute("SELECT COUNT(*) FROM messages").fetchone()
    assert c == 1
    assert m == 3


def test_ingest_all_three(tmp_db, fixtures_dir):
    for name in ("chatgpt_sample.json", "claude_sample.json", "gemini_sample.json"):
        ingest_path(tmp_db, fixtures_dir / name)
    providers = {
        r["provider"]
        for r in tmp_db.execute("SELECT DISTINCT provider FROM conversations")
    }
    assert providers == {"chatgpt", "claude", "gemini"}


def test_daily_stats_roll_up(tmp_db, fixtures_dir):
    ingest_path(tmp_db, fixtures_dir / "chatgpt_sample.json")
    rebuild_daily(tmp_db)
    s = summary(tmp_db)
    assert s["messages"] == 3
    assert s["by_provider"]["chatgpt"] == 1


def test_fts_index_populated(tmp_db, fixtures_dir):
    ingest_path(tmp_db, fixtures_dir / "chatgpt_sample.json")
    row = tmp_db.execute(
        "SELECT COUNT(*) c FROM messages_fts WHERE messages_fts MATCH 'decorators'"
    ).fetchone()
    assert row["c"] >= 1
