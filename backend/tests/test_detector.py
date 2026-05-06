from app.ingest import detect


def test_detect_each_provider(fixtures_dir):
    assert detect(fixtures_dir / "chatgpt_sample.json") == "chatgpt"
    assert detect(fixtures_dir / "claude_sample.json") == "claude"
    assert detect(fixtures_dir / "gemini_sample.json") == "gemini"
