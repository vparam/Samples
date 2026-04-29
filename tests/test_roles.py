"""Brief: User Roles.

  - Standard User: search and view content results
  - Admin: search, view, add/edit metadata tags, review issue queue
"""

from __future__ import annotations

# Note: a few endpoints (scheduler tick, ingest from URL) will actually
# *do* something when called by an admin. We use http://example.invalid/x
# URLs and a fresh DB so any side-effects fail fast and harmlessly.
ADMIN_ONLY = [
    ("GET",  "/api/admin/documents", None),
    ("GET",  "/api/admin/issues",    None),
    ("GET",  "/api/admin/analytics", None),
    ("GET",  "/api/admin/sources",   None),
    ("POST", "/api/admin/sources",   {"kind": "rss",
                                      "feed_url": "http://example.invalid/feed.xml",
                                      "default_content_type": "blog",
                                      "enabled": False}),
    ("PUT",  "/api/admin/documents/1/tags", {"tags": []}),
    ("PUT",  "/api/admin/issues/1",  {"status": "resolved"}),
    ("POST", "/api/ingest/seed",     {}),
    ("POST", "/api/admin/websub/subscribe", {"topic_url": "http://example.invalid/topic",
                                             "secret": "abcdefgh"}),
]


def _call(client, method, path, body):
    if method == "GET":
        return client.get(path)
    if method == "POST":
        return client.post(path, json=body)
    if method == "PUT":
        return client.put(path, json=body)
    raise AssertionError(method)


def test_standard_user_blocked_from_admin_endpoints(standard_client):
    for method, path, body in ADMIN_ONLY:
        r = _call(standard_client, method, path, body)
        assert r.status_code == 403, f"{method} {path} should be 403 for Standard user, got {r.status_code}"


def test_admin_can_reach_admin_endpoints(admin_client):
    """Admin must reach admin endpoints. We accept 200/2xx and 404/422
    (e.g. updating issue id 1 when none exists). What we reject is 401/403."""
    for method, path, body in ADMIN_ONLY:
        r = _call(admin_client, method, path, body)
        assert r.status_code not in (401, 403), \
            f"Admin should not be blocked from {method} {path}, got {r.status_code}: {r.text}"


def test_standard_user_can_search(standard_client):
    r = standard_client.get("/api/search", params={"q": "glass"})
    assert r.status_code == 200


def test_standard_user_can_submit_issue(standard_client):
    r = standard_client.post("/api/issues", json={
        "kind": "missing_content",
        "query_text": "fluorinated polymer phase out",
        "message": "Expected a published note on this.",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
