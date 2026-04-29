"""Test fixtures shared across the suite.

Every test runs against a fresh, isolated SQLite database. The app is
re-imported per test to ensure module-level state (the search index, the
DB path) starts clean.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Point the backend at a temp SQLite file and reload modules so the
    fresh path is used. Yields the path."""
    db_file = tmp_path / "test.sqlite3"
    monkeypatch.setenv("MJS_DB_PATH", str(db_file))
    # Force the scheduler to stay off no matter the host environment.
    monkeypatch.delenv("MJS_SCHEDULER", raising=False)

    for mod in list(sys.modules):
        if mod.startswith("prototype.backend"):
            del sys.modules[mod]
    yield db_file


@pytest.fixture
def app(tmp_db):
    from prototype.backend import main as main_mod
    return main_mod.app


@pytest.fixture
def client(app):
    """An anonymous TestClient. New cookie jar; not signed in."""
    with TestClient(app) as c:
        yield c


def _logged_in(app, email):
    c = TestClient(app)
    c.__enter__()
    r = c.post("/api/auth/login", json={"email": email})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def standard_client(app):
    """A TestClient with its own cookie jar, signed in as a Standard user.
    Distinct from `admin_client` so both can coexist in one test."""
    c = _logged_in(app, "alice@mjs-packaging.example")
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def admin_client(app):
    c = _logged_in(app, "tom@mjs-packaging.example")
    yield c
    c.__exit__(None, None, None)


# A canned in-memory fetcher used by ingestion-worker tests.
# Maps URL -> dict(status, body, etag, last_modified). Call .respond()
# with the URL it was asked for to get the response.
class FakeFetcher:
    def __init__(self):
        self.urls: dict[str, dict] = {}
        self.calls: list[tuple[str, str | None, str | None]] = []

    def serve(self, url: str, body: bytes | str, *, status: int = 200,
              etag: str | None = None, last_modified: str | None = None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.urls[url] = {"status": status, "body": body,
                          "etag": etag, "last_modified": last_modified}

    def __call__(self, url, etag, last_modified):
        self.calls.append((url, etag, last_modified))
        rec = self.urls.get(url)
        if rec is None:
            return (404, b"", None, None)
        # 304 short-circuit when the caller already has the matching ETag.
        if etag and rec["etag"] and etag == rec["etag"]:
            return (304, b"", rec["etag"], rec["last_modified"])
        return (rec["status"], rec["body"], rec["etag"], rec["last_modified"])


@pytest.fixture
def fake_fetcher():
    return FakeFetcher()
