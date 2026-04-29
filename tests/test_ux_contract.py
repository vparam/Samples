"""Brief: User Experience Requirements.

  - Clean, minimal — search bar with NL placeholder, ranked results below
  - Mobile-first responsive layout
  - No folder/category navigation
  - Loading and empty states handled gracefully
  - Short prompting guide accessible from the interface
  - Issue-reporting form available

These are UI assertions; we exercise them via the served HTML/CSS/JS
and the prompting-guide endpoint.
"""

from __future__ import annotations

import re


def test_index_html_serves(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "MJS Discovery" in r.text


def test_index_html_is_mobile_first(client):
    r = client.get("/")
    assert re.search(
        r'<meta[^>]+name="viewport"[^>]+'
        r'content="[^"]*width=device-width',
        r.text,
    ), "viewport meta tag missing"


def test_static_css_is_responsive(client):
    r = client.get("/static/style.css")
    assert r.status_code == 200
    assert "@media" in r.text


def test_search_input_uses_nl_placeholder(client):
    r = client.get("/")
    # The placeholder is conversational rather than a keyword prompt.
    assert "plain English" in r.text or "natural-language" in r.text or "Ask " in r.text


def test_no_folder_navigation_in_ui(client):
    r = client.get("/")
    body = r.text.lower()
    # The brief explicitly forbids folder/category navigation.
    for token in ("category", "categories", "folders", "browse by type",
                  "browse by category"):
        assert token not in body, f"forbidden taxonomy nav element: {token}"


def test_prompting_guide_endpoint_returns_required_sections(client):
    """Brief: 'short prompting guide accessible from the interface,
    explaining how to formulate effective queries and what the tool
    can and cannot do.'"""
    r = client.get("/api/guide")
    assert r.status_code == 200
    body = r.json()
    headings = [s["heading"].lower() for s in body["sections"]]
    assert any("does"     in h and "not"  in h for h in headings), \
        "guide must explain what the tool does NOT do"
    assert any("effective" in h or "queries" in h for h in headings), \
        "guide must explain how to formulate effective queries"


def test_issue_form_endpoint_accepts_each_issue_kind(standard_client):
    """Brief: 'users can report broken result links, incorrect content
    surfacing, or zero-result queries where they believe relevant
    content exists.'"""
    for kind in ("broken_link", "wrong_result", "missing_content", "other"):
        r = standard_client.post("/api/issues",
                                  json={"kind": kind, "message": f"test {kind}"})
        assert r.status_code == 200, kind


def test_issue_form_rejects_unknown_kind(standard_client):
    r = standard_client.post("/api/issues",
                              json={"kind": "garbage_kind", "message": "x"})
    assert r.status_code == 422
