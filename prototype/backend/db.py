"""SQLite schema and connection helper for the discovery prototype."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "discovery.sqlite3"

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
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as cx:
        cx.executescript(SCHEMA)


@contextmanager
def connect():
    cx = sqlite3.connect(DB_PATH, isolation_level=None)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    try:
        yield cx
    finally:
        cx.close()
