"""Ingestion: per-source workers (sitemap, RSS/podcast, YouTube WebSub)
plus the seed loader. All workers share the same downstream pipeline:
chunk → hash → upsert into Postgres-shaped tables → re-index.

Architecture mapping:
  §3 Per-source workers, push/poll, two-level change detection
  §3 Soft-delete on source removal
  §4 Type-aware chunking
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import httpx
from bs4 import BeautifulSoup

from . import db

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "seed.json"


# =============================================================================
# Source item + chunking
# =============================================================================

@dataclass
class SourceItem:
    source_url: str
    content_type: str
    title: str
    publish_date: str | None
    body: str
    source_tags: list[str] = field(default_factory=list)
    # Optional list of {"start": int, "text": str}. When present, used as
    # the chunk basis for podcast/video items (architecture §4 — fixed
    # ~75-second time-window chunks).
    transcript_cues: list[dict] | None = None


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def chunk_text(item: SourceItem) -> list[dict]:
    """Type-aware chunking.

    - blog / case_study / product: ~180-word chunks with the doc title
      prepended (a heading-stand-in for the prototype).
    - podcast / video: prefer transcript cues bucketed into ~75-second
      windows; fall back to ~120-word chunks if no transcript.
    """
    if item.content_type in {"podcast", "video"} and item.transcript_cues:
        return _bucket_cues(item.transcript_cues, window_seconds=75)
    if item.content_type in {"podcast", "video"}:
        size, with_ts = 120, True
    else:
        size, with_ts = 180, False

    words = item.body.split()
    chunks: list[dict] = []
    for idx, start in enumerate(range(0, len(words), size)):
        body_slice = " ".join(words[start : start + size])
        text = body_slice if with_ts else f"{item.title}. {body_slice}"
        ts = idx * 75 if with_ts else None
        chunks.append({"chunk_index": idx, "text": text, "timestamp_seconds": ts})
    if not chunks:
        chunks.append({"chunk_index": 0, "text": item.title, "timestamp_seconds": None})
    return chunks


def _bucket_cues(cues: list[dict], window_seconds: int) -> list[dict]:
    """Bucket VTT cues into fixed-time windows for deep-linkable chunks."""
    if not cues:
        return []
    chunks: list[dict] = []
    bucket_start = cues[0]["start"]
    bucket_text: list[str] = []
    for c in cues:
        if c["start"] - bucket_start >= window_seconds and bucket_text:
            chunks.append({
                "chunk_index": len(chunks),
                "text": " ".join(bucket_text).strip(),
                "timestamp_seconds": bucket_start,
            })
            bucket_start = c["start"]
            bucket_text = []
        bucket_text.append(c["text"])
    if bucket_text:
        chunks.append({
            "chunk_index": len(chunks),
            "text": " ".join(bucket_text).strip(),
            "timestamp_seconds": bucket_start,
        })
    return chunks


# =============================================================================
# Upsert + soft-delete  (architecture §3)
# =============================================================================

def upsert_item(cx, item: SourceItem) -> tuple[str, int]:
    """Insert or update a document. Returns (action, document_id)."""
    body = _normalise(item.body)
    content_hash = _hash(body)

    row = cx.execute(
        "SELECT id, content_hash FROM documents WHERE source_url = ?",
        (item.source_url,),
    ).fetchone()

    if row and row["content_hash"] == content_hash:
        cx.execute(
            "UPDATE documents SET deleted_at = NULL, fetched_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
        return ("unchanged", row["id"])

    if row:
        cx.execute(
            """UPDATE documents
               SET content_type=?, title=?, publish_date=?, body=?,
                   content_hash=?, fetched_at=?, deleted_at=NULL
               WHERE id=?""",
            (item.content_type, item.title, item.publish_date, body,
             content_hash, _now(), row["id"]),
        )
        doc_id = row["id"]
        cx.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
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


def soft_delete_missing(cx, url_prefix: str, present_urls: set[str]) -> int:
    """Mark items as deleted when they fall out of the source manifest."""
    rows = cx.execute(
        "SELECT id, source_url FROM documents WHERE deleted_at IS NULL"
    ).fetchall()
    deleted = 0
    for r in rows:
        if not r["source_url"].startswith(url_prefix):
            continue
        if r["source_url"] not in present_urls:
            cx.execute(
                "UPDATE documents SET deleted_at = ? WHERE id = ?",
                (_now(), r["id"]),
            )
            deleted += 1
    return deleted


# =============================================================================
# Seed loader
# =============================================================================

def ingest_seed() -> dict:
    raw = json.loads(SEED_PATH.read_text())
    items = [
        SourceItem(
            source_url=r["source_url"], content_type=r["content_type"],
            title=r["title"], publish_date=r.get("publish_date"),
            body=r["body"], source_tags=r.get("tags", []),
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
        counts["deleted"] = soft_delete_missing(
            cx, "https://example.mjs-packaging.com", present
        )
        cx.execute("COMMIT")
    return counts


# =============================================================================
# HTTP fetcher with two-level cache  (architecture §3)
# =============================================================================

# A fetcher takes a URL and returns (status, body_bytes, etag, last_modified).
# Tests inject a fake fetcher to avoid real network calls.
Fetcher = Callable[[str, str | None, str | None], tuple[int, bytes, str | None, str | None]]


def _http_fetch(url: str, etag: str | None, last_modified: str | None
                ) -> tuple[int, bytes, str | None, str | None]:
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        return (
            resp.status_code,
            resp.content,
            resp.headers.get("ETag"),
            resp.headers.get("Last-Modified"),
        )


def fetch_with_cache(cx, url: str, fetcher: Fetcher | None = None
                     ) -> tuple[int, bytes | None]:
    """Conditional GET. Returns (status, body) where body is None on 304."""
    fetcher = fetcher or _http_fetch
    row = cx.execute(
        "SELECT etag, last_modified FROM http_cache WHERE url = ?", (url,)
    ).fetchone()
    etag = row["etag"] if row else None
    last_mod = row["last_modified"] if row else None

    status, body, new_etag, new_last_mod = fetcher(url, etag, last_mod)

    cx.execute(
        """INSERT INTO http_cache (url, etag, last_modified, last_status, last_fetched_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET
             etag = COALESCE(excluded.etag, http_cache.etag),
             last_modified = COALESCE(excluded.last_modified, http_cache.last_modified),
             last_status = excluded.last_status,
             last_fetched_at = excluded.last_fetched_at""",
        (url, new_etag, new_last_mod, status, _now()),
    )
    if status == 304:
        return (304, None)
    return (status, body)


# =============================================================================
# Sitemap worker  (architecture §3, "use the public sitemap as the
# discovery starting point so nothing is missed")
# =============================================================================

def parse_sitemap(xml_bytes: bytes) -> list[dict]:
    """Return list of {url, lastmod} from a sitemap.xml."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    out = []
    for url_el in root.findall("s:url", ns):
        loc = (url_el.findtext("s:loc", default="", namespaces=ns) or "").strip()
        lastmod = (url_el.findtext("s:lastmod", default="", namespaces=ns) or "").strip()
        if loc:
            out.append({"url": loc, "lastmod": lastmod or None})
    return out


# Heuristic mapping from URL path to content_type so a single sitemap can
# carry mixed types without a separate manifest.
_PATH_TYPES = (
    ("/case-studies/", "case_study"),
    ("/case-study/",   "case_study"),
    ("/products/",     "product"),
    ("/product/",      "product"),
    ("/blog/",         "blog"),
    ("/news/",         "blog"),
)


def _content_type_for(url: str, default: str = "blog") -> str:
    for needle, ct in _PATH_TYPES:
        if needle in url:
            return ct
    return default


def extract_html(html_bytes: bytes, default_url: str = "") -> dict:
    """Pull title, body, publish_date, and source_tags out of an article page.

    Strips <header>, <nav>, <footer>, and script/style before reading the
    body so trivial markup churn does not invalidate the SHA-256 hash
    (architecture §3 normalisation note).
    """
    soup = BeautifulSoup(html_bytes, "html.parser")
    for sel in ("header", "nav", "footer", "script", "style", "noscript"):
        for el in soup.find_all(sel):
            el.decompose()

    def _meta(prop: str, attr: str = "property") -> str | None:
        el = soup.find("meta", attrs={attr: prop})
        if el and el.get("content"):
            return el["content"].strip()
        return None

    title = (
        _meta("og:title") or
        (soup.title.get_text(strip=True) if soup.title else None) or
        ""
    )
    publish_date = _meta("article:published_time")
    if publish_date:
        publish_date = publish_date[:10]  # YYYY-MM-DD
    tags = [
        (el.get("content") or "").strip()
        for el in soup.find_all("meta", attrs={"property": "article:tag"})
    ]
    tags = [t for t in tags if t]

    article = soup.find("article") or soup.find("main") or soup.body or soup
    body = article.get_text(" ", strip=True) if article else ""

    return {
        "title": title,
        "publish_date": publish_date,
        "body": body,
        "source_tags": tags,
    }


def ingest_sitemap(sitemap_url: str, *, fetcher: Fetcher | None = None,
                   default_content_type: str = "blog") -> dict:
    """Crawl one sitemap and ingest each <loc>.

    Two-level change detection: HTTP layer (ETag/If-Modified-Since via
    fetch_with_cache) skips unchanged pages cheaply; the SHA-256 body
    check inside upsert_item handles the rest. URLs that drop out of
    the sitemap on a subsequent run are soft-deleted.
    """
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0,
              "skipped_304": 0, "errors": 0}
    with db.connect() as cx:
        cx.execute("BEGIN")
        try:
            status, body = fetch_with_cache(cx, sitemap_url, fetcher)
            if status == 304 or not body:
                cx.execute("COMMIT")
                return counts
            entries = parse_sitemap(body)
            present_urls: set[str] = set()
            for e in entries:
                url = e["url"]
                present_urls.add(url)
                page_status, page_body = fetch_with_cache(cx, url, fetcher)
                if page_status == 304 or not page_body:
                    counts["skipped_304"] += 1
                    continue
                if page_status >= 400:
                    counts["errors"] += 1
                    continue
                meta = extract_html(page_body, url)
                if not meta["title"] or not meta["body"]:
                    counts["errors"] += 1
                    continue
                item = SourceItem(
                    source_url=url,
                    content_type=_content_type_for(url, default_content_type),
                    title=meta["title"],
                    publish_date=meta["publish_date"] or e.get("lastmod", "")[:10] or None,
                    body=meta["body"],
                    source_tags=meta["source_tags"],
                )
                action, _ = upsert_item(cx, item)
                counts[action] += 1
            # URL-prefix soft-delete: anything previously ingested under
            # the same site host that no longer appears in the sitemap.
            from urllib.parse import urlparse
            parsed = urlparse(sitemap_url)
            site_prefix = f"{parsed.scheme}://{parsed.netloc}/"
            counts["deleted"] = soft_delete_missing(cx, site_prefix, present_urls)
            cx.execute("COMMIT")
        except Exception:
            cx.execute("ROLLBACK")
            raise
    return counts


# =============================================================================
# RSS / Atom + WebVTT  (podcast worker, architecture §3)
# =============================================================================

_VTT_TS = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})\s+-->"
)


def parse_vtt(text: str) -> list[dict]:
    """Parse a WebVTT body into [{start: int_seconds, text: str}, ...]."""
    cues: list[dict] = []
    block: list[str] = []
    start_seconds: int | None = None

    def flush():
        if start_seconds is not None and block:
            cues.append({"start": start_seconds, "text": " ".join(block).strip()})

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if not line:
            flush()
            block, start_seconds = [], None
            continue
        m = _VTT_TS.search(line)
        if m:
            flush()
            block, start_seconds = [], (
                int(m["h"]) * 3600 + int(m["m"]) * 60 + int(m["s"])
            )
            continue
        if line.isdigit() and start_seconds is None:
            continue  # cue index
        block.append(line)
    flush()
    return cues


def parse_rss(xml_bytes: bytes, default_content_type: str = "blog"
              ) -> list[SourceItem]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    items: list[SourceItem] = []
    podcast_ns = {"podcast": "https://podcastindex.org/namespace/1.0"}

    # RSS 2.0
    for el in root.iter("item"):
        title = (el.findtext("title") or "").strip()
        link = (el.findtext("link") or "").strip()
        if not link:
            guid_el = el.find("guid")
            link = (guid_el.text or "").strip() if guid_el is not None else ""
        desc = (el.findtext("description") or "").strip()
        pub = (el.findtext("pubDate") or "").strip()
        # podcast:transcript URL (prefer text/vtt)
        transcript_url = None
        for t in el.findall("podcast:transcript", podcast_ns):
            if (t.get("type") or "").lower() == "text/vtt":
                transcript_url = t.get("url")
                break
        if not transcript_url:
            t = el.find("podcast:transcript", podcast_ns)
            if t is not None:
                transcript_url = t.get("url")
        if title and link:
            items.append(SourceItem(
                source_url=link, content_type=default_content_type,
                title=title, publish_date=pub or None,
                body=desc or title, source_tags=[],
                transcript_cues=None,
            ))
            # Stash transcript URL for the loader to fetch (out-of-band attr)
            items[-1].__dict__["_transcript_url"] = transcript_url

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
                source_url=link, content_type=default_content_type,
                title=title, publish_date=pub or None,
                body=body, source_tags=[],
            ))
    return items


def ingest_rss(feed_url: str, content_type: str = "blog",
               *, fetcher: Fetcher | None = None) -> dict:
    """Fetch an RSS/Atom feed; if it carries WebVTT transcripts, fetch
    those too and chunk by time window. Soft-delete handled at the URL
    prefix level."""
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0,
              "skipped_304": 0, "errors": 0}
    with db.connect() as cx:
        cx.execute("BEGIN")
        try:
            status, body = fetch_with_cache(cx, feed_url, fetcher)
            if status == 304 or not body:
                cx.execute("COMMIT")
                return counts
            items = parse_rss(body, default_content_type=content_type)
            for it in items:
                t_url = it.__dict__.get("_transcript_url")
                if t_url:
                    t_status, t_body = fetch_with_cache(cx, t_url, fetcher)
                    if t_body:
                        try:
                            it.transcript_cues = parse_vtt(t_body.decode("utf-8", "ignore"))
                        except Exception:
                            it.transcript_cues = None
                action, _ = upsert_item(cx, it)
                counts[action] += 1
            cx.execute("COMMIT")
        except Exception:
            cx.execute("ROLLBACK")
            raise
    return counts


# =============================================================================
# YouTube WebSub ingest  (architecture §3, push pipeline)
# =============================================================================

def parse_youtube_atom(xml_bytes: bytes) -> list[SourceItem]:
    """Parse a YouTube WebSub Atom payload into SourceItems."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom",
          "yt": "http://www.youtube.com/xml/schemas/2015"}
    items: list[SourceItem] = []
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        link_el = entry.find("a:link", ns)
        link = link_el.get("href").strip() if link_el is not None else ""
        published = (entry.findtext("a:published", default="", namespaces=ns) or "").strip()
        if not (title and video_id and link):
            continue
        items.append(SourceItem(
            source_url=link,
            content_type="video",
            title=title,
            publish_date=published[:10] if published else None,
            # Production: pull description + caption_track via YouTube
            # Data API. Local prototype stores a stub body so the item is
            # discoverable; admin can backfill via tag editor.
            body=f"{title} — pending caption fetch (video id {video_id}).",
            source_tags=[],
        ))
    return items


def ingest_youtube_payload(xml_bytes: bytes) -> dict:
    """Idempotent push-ingest from a verified WebSub callback body."""
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "errors": 0}
    items = parse_youtube_atom(xml_bytes)
    if not items:
        counts["errors"] = 1
        return counts
    with db.connect() as cx:
        cx.execute("BEGIN")
        for it in items:
            action, _ = upsert_item(cx, it)
            counts[action] = counts.get(action, 0) + 1
        cx.execute("COMMIT")
    return counts


# =============================================================================
# Source-table-driven scheduling helpers
# =============================================================================

def list_sources_table() -> list[dict]:
    with db.connect() as cx:
        rows = cx.execute(
            "SELECT * FROM sources ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_source(kind: str, feed_url: str, default_content_type: str,
                  enabled: bool = True, poll_interval_seconds: int = 300) -> int:
    with db.connect() as cx:
        cur = cx.execute(
            """INSERT INTO sources
                 (kind, feed_url, default_content_type, enabled, poll_interval_seconds)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(feed_url) DO UPDATE SET
                 enabled = excluded.enabled,
                 poll_interval_seconds = excluded.poll_interval_seconds""",
            (kind, feed_url, default_content_type,
             1 if enabled else 0, poll_interval_seconds),
        )
    return cur.lastrowid or 0


def list_sources() -> list[dict]:
    with db.connect() as cx:
        rows = cx.execute(
            """SELECT content_type, COUNT(*) AS n
               FROM documents WHERE deleted_at IS NULL
               GROUP BY content_type ORDER BY content_type"""
        ).fetchall()
    return [dict(r) for r in rows]
