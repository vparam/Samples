"""Brief: Ingestion and Indexing.

  - Automatic discovery and retrieval from every channel (sitemap, RSS, YouTube)
  - Change detection — skip unchanged content on subsequent runs
  - ~5-minute refresh cadence (scheduler with per-source poll interval)
  - Auto metadata extraction: title, source URL, content type, publish date
  - Admin can add/correct metadata tags without re-scraping
  - Removed source content excluded from results promptly
"""

from __future__ import annotations

from pathlib import Path

import pytest


SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "sources"


# ----------------------------------------------------------------------------
# Sitemap worker  (architecture §3, brief: 'use the public sitemap')
# ----------------------------------------------------------------------------

SITEMAP_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.mjs.example/blog/post-a</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://www.mjs.example/case-studies/foo</loc><lastmod>2026-03-01</lastmod></url>
</urlset>
"""

PAGE_A = """<html><head>
  <title>Post A — MJS</title>
  <meta property="og:title" content="Post A" />
  <meta property="article:published_time" content="2026-04-01T00:00:00Z" />
  <meta property="article:tag" content="alpha" />
  <meta property="article:tag" content="beta" />
</head><body>
  <header>nav</header>
  <article><h1>Post A</h1><p>Body of post A. Discusses sustainable packaging.</p></article>
  <footer>copyright</footer>
</body></html>"""

PAGE_FOO = """<html><head>
  <title>Case Foo</title>
  <meta property="article:published_time" content="2026-03-01T00:00:00Z" />
</head><body><article><h1>Case Foo</h1><p>Foo case study body.</p></article></body></html>"""


def _seed_sitemap_fetcher(fake):
    fake.serve("https://www.mjs.example/sitemap.xml", SITEMAP_XML, etag='"v1"')
    fake.serve("https://www.mjs.example/blog/post-a", PAGE_A, etag='"a1"')
    fake.serve("https://www.mjs.example/case-studies/foo", PAGE_FOO, etag='"f1"')


def test_sitemap_ingest_indexes_each_url(tmp_db, fake_fetcher):
    from prototype.backend import db, ingestion
    db.init_db()
    _seed_sitemap_fetcher(fake_fetcher)
    counts = ingestion.ingest_sitemap(
        "https://www.mjs.example/sitemap.xml",
        fetcher=fake_fetcher,
    )
    assert counts["inserted"] == 2

    with db.connect() as cx:
        rows = cx.execute(
            "SELECT source_url, content_type, title, publish_date "
            "FROM documents WHERE deleted_at IS NULL ORDER BY source_url"
        ).fetchall()
    types = {r["source_url"]: r["content_type"] for r in rows}
    assert types["https://www.mjs.example/blog/post-a"]      == "blog"
    assert types["https://www.mjs.example/case-studies/foo"] == "case_study"
    titles = {r["title"] for r in rows}
    assert "Post A" in titles


def test_sitemap_change_detection_skips_unchanged_runs(tmp_db, fake_fetcher):
    """Brief: 'already-indexed content that has not changed is skipped on
    subsequent runs'."""
    from prototype.backend import db, ingestion
    db.init_db()
    _seed_sitemap_fetcher(fake_fetcher)
    ingestion.ingest_sitemap("https://www.mjs.example/sitemap.xml",
                             fetcher=fake_fetcher)
    fake_fetcher.calls.clear()
    counts = ingestion.ingest_sitemap("https://www.mjs.example/sitemap.xml",
                                      fetcher=fake_fetcher)
    # Sitemap + each page returned 304 because ETags match
    assert counts["inserted"] == 0
    assert counts["updated"] == 0
    # Every conditional request sent the prior ETag
    sent_etags = [etag for url, etag, _ in fake_fetcher.calls if etag]
    assert sent_etags, "expected If-None-Match on the second run"


def test_sitemap_soft_deletes_removed_urls(tmp_db, fake_fetcher):
    """Brief: 'Removed or unpublished source content must be excluded
    from results promptly.'"""
    from prototype.backend import db, ingestion
    db.init_db()
    _seed_sitemap_fetcher(fake_fetcher)
    ingestion.ingest_sitemap("https://www.mjs.example/sitemap.xml",
                             fetcher=fake_fetcher)

    # Subsequent run — sitemap shrinks, dropping the case study. Use a
    # different ETag so the body is re-read.
    new_sitemap = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.mjs.example/blog/post-a</loc><lastmod>2026-04-01</lastmod></url>
</urlset>
"""
    fake_fetcher.serve("https://www.mjs.example/sitemap.xml", new_sitemap, etag='"v2"')
    counts = ingestion.ingest_sitemap("https://www.mjs.example/sitemap.xml",
                                      fetcher=fake_fetcher)
    assert counts["deleted"] == 1
    with db.connect() as cx:
        alive = cx.execute(
            "SELECT source_url FROM documents WHERE deleted_at IS NULL"
        ).fetchall()
    urls = {r["source_url"] for r in alive}
    assert "https://www.mjs.example/blog/post-a" in urls
    assert "https://www.mjs.example/case-studies/foo" not in urls


def test_extract_html_strips_chrome_and_pulls_meta(tmp_db):
    from prototype.backend import ingestion
    out = ingestion.extract_html(PAGE_A.encode())
    assert out["title"] == "Post A"
    assert out["publish_date"] == "2026-04-01"
    assert "alpha" in out["source_tags"] and "beta" in out["source_tags"]
    assert "copyright" not in out["body"], "footer should be stripped"
    assert "nav" not in out["body"], "header should be stripped"


# ----------------------------------------------------------------------------
# RSS / Podcast worker, including WebVTT transcript handling
# ----------------------------------------------------------------------------

PODCAST_FEED = (SAMPLES / "podcast-feed.xml").read_text()
VTT = (SAMPLES / "podcast-transcript.vtt").read_text()


def test_rss_with_vtt_transcript_chunks_by_time_window(tmp_db, fake_fetcher):
    """Architecture §4: 'fixed time-window chunks (~75 seconds), each
    carrying the start timestamp.'"""
    from prototype.backend import db, ingestion
    db.init_db()
    fake_fetcher.serve("https://feeds.mjs.example/podcast.xml", PODCAST_FEED)
    fake_fetcher.serve(
        "https://feeds.mjspackaging.example/podcast/ep21.vtt", VTT
    )
    fake_fetcher.serve(
        "https://feeds.mjspackaging.example/podcast/ep19.vtt", "WEBVTT\n\n"
    )
    counts = ingestion.ingest_rss(
        "https://feeds.mjs.example/podcast.xml",
        content_type="podcast",
        fetcher=fake_fetcher,
    )
    assert counts["inserted"] >= 1
    with db.connect() as cx:
        chunks = cx.execute(
            """SELECT c.timestamp_seconds, c.text
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE d.source_url LIKE '%ep-21%'
               ORDER BY c.chunk_index"""
        ).fetchall()
    assert chunks, "expected chunks for ep-21"
    # At least one chunk must carry a non-zero timestamp (deep-link)
    assert any((c["timestamp_seconds"] or 0) > 0 for c in chunks)


def test_parse_vtt_returns_cues_with_seconds(tmp_db):
    from prototype.backend import ingestion
    cues = ingestion.parse_vtt(VTT)
    assert len(cues) >= 5
    starts = [c["start"] for c in cues]
    assert starts == sorted(starts)
    assert any(c["start"] >= 60 for c in cues)


# ----------------------------------------------------------------------------
# YouTube WebSub push pipeline
# ----------------------------------------------------------------------------

def test_youtube_websub_atom_payload_ingested(tmp_db):
    from prototype.backend import db, ingestion
    db.init_db()
    payload = (SAMPLES / "youtube-websub-callback.xml").read_bytes()
    counts = ingestion.ingest_youtube_payload(payload)
    assert counts["inserted"] == 1
    with db.connect() as cx:
        row = cx.execute(
            "SELECT title, source_url, content_type, publish_date "
            "FROM documents WHERE source_url LIKE '%youtube.com%'"
        ).fetchone()
    assert row is not None
    assert row["content_type"] == "video"
    assert row["title"].startswith("A tour")
    assert row["publish_date"] == "2026-02-22"


# ----------------------------------------------------------------------------
# Auto metadata extraction (brief: title, source URL, content type, publish date)
# ----------------------------------------------------------------------------

def test_seed_documents_carry_required_metadata(tmp_db):
    from prototype.backend import db, ingestion
    db.init_db()
    ingestion.ingest_seed()
    with db.connect() as cx:
        rows = cx.execute(
            "SELECT title, source_url, content_type, publish_date "
            "FROM documents WHERE deleted_at IS NULL"
        ).fetchall()
    assert rows
    for r in rows:
        assert r["title"]
        assert r["source_url"].startswith("http")
        assert r["content_type"] in {"blog", "case_study", "product",
                                     "podcast", "video"}
        assert r["publish_date"], r["title"]


def test_change_detection_skips_unchanged_seed_runs(tmp_db):
    from prototype.backend import db, ingestion
    db.init_db()
    first = ingestion.ingest_seed()
    second = ingestion.ingest_seed()
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert second["unchanged"] == first["inserted"] + first["unchanged"]
