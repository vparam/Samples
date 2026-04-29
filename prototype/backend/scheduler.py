"""Periodic ingestion driver. Architecture §3: 5-minute polling fallback
for sources that cannot push (sitemap; podcast feeds without a hub).

Designed so tests can drive it deterministically:
  - run_one_cycle() runs every due source once and returns a per-source
    summary. No sleeping, no thread.
  - start_background() launches a daemon thread that loops with sleeps
    between cycles. Off by default; only enabled when MJS_SCHEDULER=on.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from . import db, ingestion

log = logging.getLogger("mjs.scheduler")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_due(row: dict, now: datetime) -> bool:
    if not row["enabled"]:
        return False
    if not row["last_run_at"]:
        return True
    try:
        last = datetime.fromisoformat(row["last_run_at"])
    except ValueError:
        return True
    return (now - last).total_seconds() >= row["poll_interval_seconds"]


def run_one_cycle(*, fetcher: ingestion.Fetcher | None = None,
                  now: datetime | None = None) -> list[dict]:
    """Run every due source once. Returns per-source result rows."""
    now = now or _now_utc()
    out: list[dict] = []
    for src in ingestion.list_sources_table():
        if not _is_due(src, now):
            continue
        kind = src["kind"]
        url = src["feed_url"]
        ct = src["default_content_type"]
        result: dict[str, Any] = {"source_id": src["id"], "kind": kind, "feed_url": url}
        try:
            if kind == "sitemap":
                result["counts"] = ingestion.ingest_sitemap(
                    url, fetcher=fetcher, default_content_type=ct,
                )
            elif kind == "rss":
                result["counts"] = ingestion.ingest_rss(
                    url, content_type=ct, fetcher=fetcher,
                )
            elif kind == "youtube_websub":
                # Push-only source. Polling is a no-op; we keep the row
                # for visibility in the admin UI.
                result["counts"] = {"skipped": "push_only"}
            else:
                result["error"] = f"unknown source kind: {kind}"
            status = "ok"
        except Exception as e:  # noqa: BLE001
            log.exception("ingest failed for %s", url)
            result["error"] = str(e)
            status = "error"
        with db.connect() as cx:
            cx.execute(
                "UPDATE sources SET last_run_at=?, last_run_status=? WHERE id=?",
                (now.isoformat(timespec="seconds"), status, src["id"]),
            )
        out.append(result)
    return out


_thread: threading.Thread | None = None
_stop = threading.Event()


def _loop(tick_seconds: float) -> None:
    while not _stop.is_set():
        try:
            run_one_cycle()
        except Exception:  # noqa: BLE001
            log.exception("scheduler cycle crashed")
        _stop.wait(tick_seconds)


def start_background(tick_seconds: float = 30.0) -> None:
    """Launch the scheduler in a daemon thread. No-op if already running.
    Off unless MJS_SCHEDULER=on (avoids competing with tests)."""
    if os.environ.get("MJS_SCHEDULER", "").lower() not in ("1", "on", "true"):
        return
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(tick_seconds,),
                               name="mjs-scheduler", daemon=True)
    _thread.start()


def stop_background(timeout: float = 2.0) -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=timeout)
