"""Brief: '~5-minute freshness target ... while not hammering source
systems unnecessarily.' Architecture §3: 5-minute polling fallback.

The scheduler runs every due source once per cycle. Sources have
poll_interval_seconds; a source is 'due' when last_run_at is older
than that. Tests drive run_one_cycle() directly to avoid timing flake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.mjs.example/blog/x</loc></url>
</urlset>"""

PAGE = """<html><head>
<title>X</title><meta property="article:published_time" content="2026-04-01T00:00:00Z"/>
</head><body><article>X body about packaging.</article></body></html>"""


def test_scheduler_runs_due_sources_once_per_cycle(tmp_db, fake_fetcher):
    from prototype.backend import db, ingestion, scheduler
    db.init_db()

    fake_fetcher.serve("https://www.mjs.example/sitemap.xml", SITEMAP, etag='"v1"')
    fake_fetcher.serve("https://www.mjs.example/blog/x", PAGE, etag='"x1"')

    ingestion.upsert_source(
        kind="sitemap",
        feed_url="https://www.mjs.example/sitemap.xml",
        default_content_type="blog",
        poll_interval_seconds=300,
    )

    results = scheduler.run_one_cycle(fetcher=fake_fetcher)
    assert len(results) == 1
    assert results[0]["counts"]["inserted"] == 1


def test_scheduler_does_not_hammer_within_poll_interval(tmp_db, fake_fetcher):
    """Brief: 'while not hammering source systems unnecessarily'."""
    from prototype.backend import db, ingestion, scheduler
    db.init_db()
    fake_fetcher.serve("https://www.mjs.example/sitemap.xml", SITEMAP, etag='"v1"')
    fake_fetcher.serve("https://www.mjs.example/blog/x", PAGE, etag='"x1"')

    ingestion.upsert_source(
        kind="sitemap",
        feed_url="https://www.mjs.example/sitemap.xml",
        default_content_type="blog",
        poll_interval_seconds=300,
    )
    scheduler.run_one_cycle(fetcher=fake_fetcher)
    fake_fetcher.calls.clear()

    # Second cycle just one second later — source is not yet due.
    later = datetime.now(timezone.utc) + timedelta(seconds=1)
    results = scheduler.run_one_cycle(fetcher=fake_fetcher, now=later)
    assert results == [], "source was polled before its interval elapsed"
    assert fake_fetcher.calls == []


def test_scheduler_meets_5_minute_freshness_target(tmp_db, fake_fetcher):
    """A source with the default 300-second poll interval is due again
    once at least 300 seconds have passed since its last run."""
    from prototype.backend import db, ingestion, scheduler
    db.init_db()
    fake_fetcher.serve("https://www.mjs.example/sitemap.xml", SITEMAP, etag='"v1"')
    fake_fetcher.serve("https://www.mjs.example/blog/x", PAGE, etag='"x1"')

    ingestion.upsert_source(
        kind="sitemap",
        feed_url="https://www.mjs.example/sitemap.xml",
        default_content_type="blog",
        poll_interval_seconds=300,
    )
    scheduler.run_one_cycle(fetcher=fake_fetcher)

    # 5 minutes later, source becomes due again.
    later = datetime.now(timezone.utc) + timedelta(seconds=301)
    results = scheduler.run_one_cycle(fetcher=fake_fetcher, now=later)
    assert len(results) == 1


def test_disabled_source_is_not_polled(tmp_db, fake_fetcher):
    from prototype.backend import db, ingestion, scheduler
    db.init_db()
    fake_fetcher.serve("https://www.mjs.example/sitemap.xml", SITEMAP, etag='"v1"')
    fake_fetcher.serve("https://www.mjs.example/blog/x", PAGE, etag='"x1"')

    ingestion.upsert_source(
        kind="sitemap",
        feed_url="https://www.mjs.example/sitemap.xml",
        default_content_type="blog",
        enabled=False,
    )
    results = scheduler.run_one_cycle(fetcher=fake_fetcher)
    assert results == []
    assert fake_fetcher.calls == []


def test_admin_can_trigger_scheduler_tick_via_api(admin_client, fake_fetcher):
    """The admin tick endpoint runs run_one_cycle synchronously. Useful
    for demos and the CI eval harness."""
    from prototype.backend import ingestion
    ingestion.upsert_source(
        kind="rss",
        feed_url="https://example.invalid/feed.xml",
        default_content_type="blog",
        poll_interval_seconds=1,
    )
    r = admin_client.post("/api/admin/scheduler/tick")
    assert r.status_code == 200
    assert isinstance(r.json()["ran"], list)
