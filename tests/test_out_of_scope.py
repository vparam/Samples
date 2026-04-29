"""Brief: 'Explicitly Out of Scope ... do NOT spend time on the following.'

These tests guard against accidentally reintroducing scope: AI synthesis,
content-suppression admin tooling, shareable saved-search links. We assert
the absence of any such surface in the API contract.
"""

from __future__ import annotations


def test_no_synthesis_endpoint_exists(client):
    """No `/api/answer`, `/api/synthesise`, or similar."""
    for path in ("/api/answer", "/api/answers", "/api/synthesise",
                 "/api/synthesize", "/api/summarise", "/api/summarize",
                 "/api/chat", "/api/completion"):
        r = client.get(path)
        assert r.status_code == 404, f"unexpected synthesis endpoint: {path}"


def test_no_shareable_saved_search_endpoints(client):
    for path in ("/api/saved-searches", "/api/share", "/api/links/share"):
        r = client.get(path)
        assert r.status_code == 404


def test_no_content_suppression_endpoints(client):
    for path in ("/api/admin/suppress", "/api/admin/hide-document",
                 "/api/admin/blacklist"):
        r = client.get(path)
        assert r.status_code == 404


def test_no_pdf_ingestion_endpoint(client):
    r = client.get("/api/ingest/pdf")
    assert r.status_code == 404
