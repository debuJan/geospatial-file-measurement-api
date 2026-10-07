"""Pytest fixtures: isolated app with temp database and upload dir.

Environment variables are set at import time -- BEFORE the app modules are
imported -- because settings are read from the environment on import.
"""
import os
import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent

# Isolate persistent state before importing the app.
os.environ["GEOAPI_DATABASE_URL"] = f"sqlite:///{TEST_DIR / 'test.db'}"
os.environ["GEOAPI_UPLOAD_DIR"] = str(TEST_DIR / "test_uploads")

sys.path.insert(0, str(TEST_DIR.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh TestClient per test: clean tables + per-test upload directory."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_dir))

    with TestClient(app) as test_client:
        yield test_client
