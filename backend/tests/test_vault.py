from app.ingest.service import ingest_path
from app.vault import export_vault


def test_vault_export_shape(tmp_db, fixtures_dir, tmp_path):
    ingest_path(tmp_db, fixtures_dir / "chatgpt_sample.json")
    ingest_path(tmp_db, fixtures_dir / "claude_sample.json")
    dest = tmp_path / "vault"
    result = export_vault(tmp_db, dest)
    assert result["conversations"] == 2
    # Each conversation note exists under the provider folder.
    conv_files = list((dest / "Conversations").rglob("*.md"))
    assert len(conv_files) == 2
    # Daily notes and index exist.
    assert (dest / "_Index.md").exists()
    assert list((dest / "Daily").glob("*.md"))
    # Frontmatter is present on every conversation note.
    for p in conv_files:
        head = p.read_text(encoding="utf-8").splitlines()
        assert head[0] == "---"
        assert any(line.startswith("provider:") for line in head[:15])
