"""SQLite schema and connection helper for the discovery prototype."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

_DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "discovery.sqlite3"
)


def db_path() -> Path:
    """Resolved at call time so tests can override via MJS_DB_PATH."""
    p = os.environ.get("MJS_DB_PATH")
    return Path(p) if p else _DEFAULT_DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    title TEXT NOT NULL,
    publish_date TEXT,
    body TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    timestamp_seconds INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);

CREATE TABLE IF NOT EXISTS admin_overrides (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    tags TEXT NOT NULL DEFAULT '[]',
    updated_by TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS source_tags (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    tags TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    user_email TEXT,
    query_text TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    no_results INTEGER NOT NULL DEFAULT 0,
    top_result_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queries_created ON queries(created_at);
CREATE INDEX IF NOT EXISTS idx_queries_no_results ON queries(no_results);

CREATE TABLE IF NOT EXISTS clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER REFERENCES queries(id) ON DELETE SET NULL,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    content_type TEXT,
    position INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    clicked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    user_email TEXT,
    kind TEXT NOT NULL,
    query_text TEXT,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

-- HTTP-layer change-detection cache (architecture §3, two-level check).
-- Keyed by URL; stores last ETag / Last-Modified / status from the source.
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    last_status INTEGER,
    last_fetched_at TEXT NOT NULL
);

-- Configured ingestion sources. The scheduler iterates this table.
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('sitemap','rss','youtube_websub')),
    feed_url TEXT NOT NULL UNIQUE,
    default_content_type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    poll_interval_seconds INTEGER NOT NULL DEFAULT 300,
    last_run_at TEXT,
    last_run_status TEXT
);

-- WebSub subscription state. Used by the YouTube push pipeline.
CREATE TABLE IF NOT EXISTS websub_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_url TEXT NOT NULL UNIQUE,
    secret TEXT NOT NULL,
    verified_at TEXT,
    expires_at TEXT
);
"""


def init_db() -> None:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with connect() as cx:
        cx.executescript(SCHEMA)


@contextmanager
def connect():
    cx = sqlite3.connect(db_path(), isolation_level=None)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    try:
        yield cx
    finally:
        cx.close()
