"""WebSub callback contract: subscription verification + signed delivery.

Architecture §3 push pipeline. Brief: 'Automatic discovery and retrieval
of content from every channel listed above' — YouTube is one of the
listed channels, and WebSub is the production push path.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

ATOM = (Path(__file__).resolve().parents[1]
        / "samples" / "sources" / "youtube-websub-callback.xml").read_bytes()
TOPIC = "https://www.youtube.com/xml/feeds/videos.xml?channel_id=UC_MJS_PACKAGING"
SECRET = "demo-shared-secret"


def _subscribe(admin_client):
    r = admin_client.post("/api/admin/websub/subscribe",
                          json={"topic_url": TOPIC, "secret": SECRET})
    assert r.status_code == 200


def test_websub_verify_unknown_topic_404s(client):
    r = client.get("/webhooks/youtube/websub", params={
        "hub.challenge": "abc123",
        "hub.mode": "subscribe",
        "hub.topic": "https://example.com/unknown",
    })
    assert r.status_code == 404


def test_websub_verify_returns_challenge_for_known_topic(admin_client):
    _subscribe(admin_client)
    r = admin_client.get("/webhooks/youtube/websub", params={
        "hub.challenge": "abc123",
        "hub.mode": "subscribe",
        "hub.topic": TOPIC,
    })
    assert r.status_code == 200
    assert r.text == "abc123"
    assert r.headers["content-type"].startswith("text/plain")


def test_websub_callback_rejects_bad_signature(client, admin_client):
    _subscribe(admin_client)
    r = client.post(
        "/webhooks/youtube/websub", content=ATOM,
        headers={"X-Hub-Signature": "sha1=deadbeef",
                 "Content-Type": "application/atom+xml"},
    )
    assert r.status_code == 403


def test_websub_callback_accepts_signed_payload_and_ingests(client, admin_client):
    _subscribe(admin_client)
    sig = hmac.new(SECRET.encode(), ATOM, hashlib.sha1).hexdigest()
    r = client.post(
        "/webhooks/youtube/websub", content=ATOM,
        headers={"X-Hub-Signature": f"sha1={sig}",
                 "Content-Type": "application/atom+xml"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # The seed corpus already includes this video URL, so the callback
    # is a successful upsert — accept either inserted or unchanged.
    # The seed corpus already carries this video URL with a different
    # body; the callback's stub body produces an `updated` action. We
    # accept any non-error upsert outcome.
    counts = body["counts"]
    actioned = (counts.get("inserted", 0)
                + counts.get("updated", 0)
                + counts.get("unchanged", 0))
    assert actioned >= 1, counts
    assert counts.get("errors", 0) == 0

    # The video is in the index — searching for it returns it.
    s = admin_client.get("/api/search", params={"q": "production line tour"})
    assert any("youtube.com/watch?v=mjs-glass-line-tour" in c["url"]
               for c in s.json()["results"])
