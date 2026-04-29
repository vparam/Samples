"""Brief: Admin features.

  - Admin can add/correct metadata tags on indexed content WITHOUT re-scraping
  - Issue queue visible to admins
  - Admin dashboard exposes top queries, zero-result queries, content
    types most surfaced/clicked, and basic usage volume over time
"""

from __future__ import annotations


def test_admin_tag_edit_does_not_rescrape_but_does_reindex(admin_client):
    """Architecture §7: admin edits write to admin_overrides and trigger
    a re-index, NOT a re-scrape. The fingerprint of "no re-scrape" is
    that the document's content_hash and fetched_at do not change."""
    from prototype.backend import db
    docs = admin_client.get("/api/admin/documents").json()["documents"]
    doc = docs[0]
    with db.connect() as cx:
        before = cx.execute(
            "SELECT content_hash, fetched_at FROM documents WHERE id = ?",
            (doc["id"],),
        ).fetchone()

    r = admin_client.put(f"/api/admin/documents/{doc['id']}/tags",
                         json={"tags": ["editorial-pick", "sales-enablement"]})
    assert r.status_code == 200

    with db.connect() as cx:
        after = cx.execute(
            "SELECT content_hash, fetched_at FROM documents WHERE id = ?",
            (doc["id"],),
        ).fetchone()
        override = cx.execute(
            "SELECT tags, updated_by FROM admin_overrides WHERE document_id = ?",
            (doc["id"],),
        ).fetchone()

    assert before["content_hash"] == after["content_hash"]
    assert before["fetched_at"]   == after["fetched_at"]
    assert override is not None
    assert "editorial-pick" in override["tags"]
    assert override["updated_by"] == "tom@mjs-packaging.example"

    # Re-index has happened: the new tag is searchable.
    s = admin_client.get("/api/search", params={"q": "editorial-pick"})
    body = s.json()
    assert body["no_results"] is False
    assert any(c["document_id"] == doc["id"] for c in body["results"])


def test_admin_can_review_and_update_issue_queue(admin_client, standard_client):
    """Brief: 'Submissions should be visible to admins.'"""
    r = standard_client.post("/api/issues", json={
        "kind": "missing_content",
        "query_text": "fluorinated polymer phase out",
        "message": "Expected a published note on this.",
    })
    assert r.status_code == 200
    issue_id = r.json()["issue_id"]

    listed = admin_client.get("/api/admin/issues").json()["issues"]
    assert any(i["id"] == issue_id for i in listed)

    upd = admin_client.put(f"/api/admin/issues/{issue_id}",
                           json={"status": "in_progress"})
    assert upd.status_code == 200
    assert upd.json()["ok"] is True


def test_admin_dashboard_exposes_required_signals(standard_client, admin_client):
    # Generate some traffic
    standard_client.get("/api/search", params={"q": "pharma-grade glass case studies"})
    standard_client.get("/api/search", params={"q": "What is the population of Tokyo?"})
    standard_client.get("/api/search", params={"q": "food-grade containers"})
    # Click the first result on the food-grade query
    body = standard_client.get(
        "/api/search", params={"q": "food-grade containers"}
    ).json()
    if body["results"]:
        c = body["results"][0]
        standard_client.post("/api/search/click", json={
            "query_id": body["query_id"], "document_id": c["document_id"],
            "position": 0, "content_type": c["content_type"],
        })

    a = admin_client.get("/api/admin/analytics").json()
    # Required signals from the brief
    assert "totals" in a
    assert {"total_queries", "zero_result_queries", "total_clicks",
            "indexed_documents"} <= set(a["totals"].keys())
    assert a["totals"]["total_queries"] >= 3
    assert a["totals"]["zero_result_queries"] >= 1

    assert "top_queries" in a and isinstance(a["top_queries"], list)
    assert "zero_result_queries" in a and isinstance(a["zero_result_queries"], list)
    assert "clicked_content_types" in a
    assert "daily_volume" in a

    zero_texts = [q["query_text"] for q in a["zero_result_queries"]]
    assert any("Tokyo" in t for t in zero_texts)


def test_query_log_carries_user_identity_for_audit(standard_client):
    """Brief: 'Authenticated user identity associated with each query for
    audit purposes.'"""
    from prototype.backend import db
    standard_client.get("/api/search", params={"q": "pharma-grade glass case studies"})
    with db.connect() as cx:
        row = cx.execute(
            "SELECT user_id, user_email FROM queries ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["user_id"] == "user-alice"
    assert row["user_email"] == "alice@mjs-packaging.example"
