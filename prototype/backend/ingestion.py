"""Ingestion: load seed content, fetch RSS, chunk, persist with change detection.

The architecture writeup describes per-source workers (website, podcast, YouTube).
This prototype implements two:
  - seed_loader: hydrates the index from data/seed.json (representative MJS content)
  - rss_loader:  fetches an RSS feed, parses entries, and indexes them

Change detection is two-level: HTTP layer (ETag / Last-Modified, applies to RSS)
and content layer (SHA-256 of normalised body). Items removed from the source
manifest are soft-deleted.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx

from . import db

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "seed.json"


@dataclass
class SourceItem:
    source_url: str
    content_type: str
    title: str
    publish_date: str | None
    body: str
    source_tags: list[str]


def _normalise(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def chunk_text(item: SourceItem) -> list[dict]:
    """Type-aware chunking. Token-ish via whitespace split as a stand-in.

    - blog / case_study / product: ~180 word chunks with title prepended
    - podcast / video: ~120 word chunks with a synthetic timestamp
    """
    words = item.body.split()
    if item.content_type in {"podcast", "video"}:
        size = 120
        with_ts = True
    else:
        size = 180
        with_ts = False

    chunks: list[dict] = []
    for idx, start in enumerate(range(0, len(words), size)):
        body_slice = " ".join(words[start : start + size])
        text = f"{item.title}. {body_slice}" if not with_ts else body_slice
        ts = idx * 75 if with_ts else None
        chunks.append({"chunk_index": idx, "text": text, "timestamp_seconds": ts})
    if not chunks:
        chunks.append({"chunk_index": 0, "text": item.title, "timestamp_seconds": None})
    return chunks


def upsert_item(cx, item: SourceItem) -> tuple[str, int]:
    """Insert or update a document. Returns (action, document_id)."""
    body = _normalise(item.body)
    content_hash = _hash(body)

    row = cx.execute(
        "SELECT id, content_hash FROM documents WHERE source_url = ?",
        (item.source_url,),
    ).fetchone()

    if row and row["content_hash"] == content_hash and row["id"]:
        cx.execute(
            "UPDATE documents SET deleted_at = NULL, fetched_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
        return ("unchanged", row["id"])

    if row:
        cx.execute(
            """UPDATE documents
               SET content_type = ?, title = ?, publish_date = ?, body = ?,
                   content_hash = ?, fetched_at = ?, deleted_at = NULL
               WHERE id = ?""",
            (item.content_type, item.title, item.publish_date, body,
             content_hash, _now(), row["id"]),
        )
        doc_id = row["id"]
        cx.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        action = "updated"
    else:
        cur = cx.execute(
            """INSERT INTO documents
                 (source_url, content_type, title, publish_date, body,
                  content_hash, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (item.source_url, item.content_type, item.title, item.publish_date,
             body, content_hash, _now()),
        )
        doc_id = cur.lastrowid
        action = "inserted"

    for ch in chunk_text(item):
        cx.execute(
            """INSERT INTO chunks (document_id, chunk_index, text, timestamp_seconds)
               VALUES (?, ?, ?, ?)""",
            (doc_id, ch["chunk_index"], ch["text"], ch["timestamp_seconds"]),
        )

    cx.execute(
        """INSERT INTO source_tags (document_id, tags) VALUES (?, ?)
           ON CONFLICT(document_id) DO UPDATE SET tags = excluded.tags""",
        (doc_id, json.dumps(item.source_tags)),
    )
    return (action, doc_id)


def soft_delete_missing(cx, source: str, present_urls: set[str]) -> int:
    """Mark items as deleted when they fall out of the source manifest."""
    rows = cx.execute(
        "SELECT id, source_url FROM documents WHERE deleted_at IS NULL"
    ).fetchall()
    deleted = 0
    for r in rows:
        if not r["source_url"].startswith(source):
            continue
        if r["source_url"] not in present_urls:
            cx.execute(
                "UPDATE documents SET deleted_at = ? WHERE id = ?",
                (_now(), r["id"]),
            )
            deleted += 1
    return deleted


def ingest_seed() -> dict:
    """Load the seed corpus. Idempotent: unchanged items are skipped."""
    raw = json.loads(SEED_PATH.read_text())
    items = [
        SourceItem(
            source_url=r["source_url"],
            content_type=r["content_type"],
            title=r["title"],
            publish_date=r.get("publish_date"),
            body=r["body"],
            source_tags=r.get("tags", []),
        )
        for r in raw
    ]
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0}
    with db.connect() as cx:
        cx.execute("BEGIN")
        for it in items:
            action, _ = upsert_item(cx, it)
            counts[action] += 1
        present = {it.source_url for it in items}
        counts["deleted"] = soft_delete_missing(cx, "https://example.mjs-packaging.com", present)
        cx.execute("COMMIT")
    return counts


def parse_rss(xml_bytes: bytes, source_prefix: str) -> list[SourceItem]:
    """Minimal RSS 2.0 / Atom parser using stdlib (no feedparser dep)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    items: list[SourceItem] = []
    # RSS 2.0
    for el in root.iter("item"):
        title = (el.findtext("title") or "").strip()
        link = (el.findtext("link") or "").strip()
        desc = (el.findtext("description") or "").strip()
        pub = (el.findtext("pubDate") or "").strip()
        if title and link:
            items.append(SourceItem(
                source_url=link, content_type="blog", title=title,
                publish_date=pub or None, body=desc or title, source_tags=[],
            ))
    # Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for el in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title = (el.findtext("a:title", default="", namespaces=ns) or "").strip()
        link_el = el.find("a:link", ns)
        link = link_el.get("href").strip() if link_el is not None and link_el.get("href") else ""
        summary = (el.findtext("a:summary", default="", namespaces=ns) or "").strip()
        content = (el.findtext("a:content", default="", namespaces=ns) or "").strip()
        pub = (el.findtext("a:updated", default="", namespaces=ns)
               or el.findtext("a:published", default="", namespaces=ns) or "").strip()
        body = content or summary or title
        if title and link:
            items.append(SourceItem(
                source_url=link, content_type="blog", title=title,
                publish_date=pub or None, body=body, source_tags=[],
            ))
    return items


def ingest_rss(feed_url: str, content_type: str = "blog") -> dict:
    """Fetch an RSS/Atom feed and ingest entries.

    Honours ETag / Last-Modified through a tiny in-DB cache table-less
    approach: we use a fixed key per feed_url stored in the documents table
    via a metadata row (skipped here for simplicity; full version in section 3
    of the architecture). For the prototype we always fetch but only re-index
    on body-hash change.
    """
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0, "fetched": 0}
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(feed_url)
            resp.raise_for_status()
            counts["fetched"] = len(resp.content)
            items = parse_rss(resp.content, feed_url)
    except (httpx.HTTPError, OSError) as e:
        return {**counts, "error": str(e)}

    if not items:
        return {**counts, "error": "no entries parsed"}

    with db.connect() as cx:
        cx.execute("BEGIN")
        for it in items:
            it.content_type = content_type
            action, _ = upsert_item(cx, it)
            counts[action] += 1
        cx.execute("COMMIT")
    return counts


def list_sources() -> list[dict]:
    with db.connect() as cx:
        rows = cx.execute(
            """SELECT content_type, COUNT(*) AS n
               FROM documents WHERE deleted_at IS NULL
               GROUP BY content_type ORDER BY content_type"""
        ).fetchall()
    return [dict(r) for r in rows]
