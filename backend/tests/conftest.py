"""Shared fixtures for backend tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ULLE_DB", str(db_path))
    monkeypatch.setenv("ULLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ULLE_MODEL_CACHE", str(tmp_path / "models"))
    # Force re-load of the settings module-level instance.
    from app import config as cfg

    cfg.settings = cfg.Settings.load()
    from app.db import connect, init_db

    init_db(db_path)
    db = connect(db_path)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
