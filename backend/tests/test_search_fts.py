from app.ingest.service import ingest_path
from app.search import search


def test_fts_search_returns_hit(tmp_db, fixtures_dir):
    ingest_path(tmp_db, fixtures_dir / "chatgpt_sample.json")
    hits = search(tmp_db, "decorators", mode="fts")
    assert hits
    assert any("decorators" in (h.content or "").lower() for h in hits)


def test_search_empty_query(tmp_db):
    assert search(tmp_db, "") == []
