from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).parent / ".runtime"
TEST_DB = TEST_ROOT / "test_app.db"
TEST_STORAGE = TEST_ROOT / "uploads"

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["STORAGE_DIR"] = str(TEST_STORAGE)
os.environ["CORS_ALLOW_ORIGINS"] = "http://localhost:5173"
os.environ["TRUSTED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["MAX_UPLOAD_SIZE_MB"] = "2"
os.environ["DEPLOYMENT_MODE"] = "local"
os.environ["MAX_TEXT_BYTES"] = "1000000"

from fastapi.testclient import TestClient  # noqa: E402

from app.production_main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def clean_runtime():
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    yield
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client
