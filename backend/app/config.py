"""Configuration. All paths local. No network required."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    uploads_dir: Path
    exports_dir: Path
    model_cache_dir: Path
    embedding_model: str
    host: str
    port: int

    @classmethod
    def load(cls) -> Settings:
        root = Path(__file__).resolve().parents[2]
        data_dir = _env_path("ULLE_DATA_DIR", root / "data")
        data_dir.mkdir(parents=True, exist_ok=True)
        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        exports = data_dir / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        model_cache = _env_path("ULLE_MODEL_CACHE", data_dir / "models")
        model_cache.mkdir(parents=True, exist_ok=True)
        return cls(
            data_dir=data_dir,
            db_path=_env_path("ULLE_DB", data_dir / "ulle.db"),
            uploads_dir=uploads,
            exports_dir=exports,
            model_cache_dir=model_cache,
            embedding_model=os.environ.get(
                "ULLE_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            host=os.environ.get("ULLE_HOST", "127.0.0.1"),
            port=int(os.environ.get("ULLE_PORT", "8000")),
        )


settings = Settings.load()
