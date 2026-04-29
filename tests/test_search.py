"""Brief: Search and Retrieval.

  - User submits a NL question via the search interface
  - System returns a ranked list of result cards linking back to the source
  - Each card displays: title, content type, publish date, short excerpt
  - Recency influences ranking
  - No-results state when no relevant content
  - Source links only — no AI synthesis (covered by absence of any
    summary/answer field in the response)

Plus the example queries listed in the brief.
"""

from __future__ import annotations


REAL_QUERIES = [
    "Why should a customer work with us?",
    "What case studies do we have around food-grade packaging?",
    "Do we have any content about sustainable materials?",
    "What have we published recently about supply chain?",
    "I want content around why a customer should work with us",
]


def test_search_returns_ranked_results_for_brief_queries(standard_client):
    for q in REAL_QUERIES:
        r = standard_client.get("/api/search", params={"q": q})
        assert r.status_code == 200, q
        body = r.json()
        assert body["no_results"] is False, f"unexpected no_results for: {q}"
        assert len(body["results"]) >= 1
        # Ranked: scores monotonically non-increasing
        scores = [it["score"] for it in body["results"]]
        assert scores == sorted(scores, reverse=True), q


def test_result_card_shape_matches_brief(standard_client):
    """Each result card displays: title, content type, publish date, excerpt,
    and a link back to the source URL."""
    r = standard_client.get("/api/search",
                            params={"q": "pharma-grade glass case studies"})
    body = r.json()
    assert body["results"], body
    card = body["results"][0]
    for field in ("title", "content_type", "publish_date", "url", "excerpt"):
        assert field in card and card[field], f"missing field: {field}"
    # Source link is absolute and points outside the app
    assert card["url"].startswith("http")


def test_response_contains_no_synthesised_answer_field(standard_client):
    """Architecture §6 layer 1: the API has no LLM in the response path.
    Validate the contract by asserting absence of any answer/summary
    field, which would indicate generation."""
    r = standard_client.get("/api/search", params={"q": "glass"})
    body = r.json()
    forbidden = {"answer", "answers", "summary", "summarisation",
                 "completion", "generated", "synthesis"}
    assert not (forbidden & set(body.keys())), \
        f"response leaked a generation field: {set(body.keys()) & forbidden}"
    for r in body.get("results", []):
        assert not (forbidden & set(r.keys())), r


def test_video_url_is_timestamp_deep_linked(standard_client):
    """Architecture §4: video chunk hits should resolve to youtu.be?t=NN."""
    r = standard_client.get("/api/search",
                            params={"q": "annealing oven calibration"})
    body = r.json()
    matches = [c for c in body["results"]
               if c["content_type"] == "video" and "youtube.com" in c["url"]]
    if matches:
        # When the matched chunk has a timestamp, the URL carries &t=
        assert any("&t=" in c["url"] for c in matches), \
            "expected at least one video result to be deep-linked"


def test_recency_influences_ranking_when_relevance_close(standard_client):
    """Recency is a multiplier (≤1.3×) — when two docs are similarly
    relevant, the newer one wins. The brief's 'recent supply chain' query
    is the canonical example: April-2026 supply-chain update beats Q1-2026
    retrospective."""
    r = standard_client.get("/api/search",
                            params={"q": "recent supply chain"})
    body = r.json()
    titles = [c["title"] for c in body["results"]]
    assert any("April 2026" in t or "Q1 2026" in t for t in titles)
    # The April update should appear ahead of the Q1 retrospective when
    # both are present.
    if any("April 2026" in t for t in titles) and any("Q1 2026" in t for t in titles):
        idx_recent = next(i for i, t in enumerate(titles) if "April 2026" in t)
        idx_older  = next(i for i, t in enumerate(titles) if "Q1 2026" in t)
        assert idx_recent < idx_older


def test_query_max_length_enforced(standard_client):
    too_long = "x" * 501
    r = standard_client.get("/api/search", params={"q": too_long})
    assert r.status_code == 422


def test_empty_query_rejected(standard_client):
    r = standard_client.get("/api/search", params={"q": ""})
    assert r.status_code == 422


# ----------------------------------------------------------------------------
# Improvements landed after the first evaluation pass (EVALUATION.md)
# ----------------------------------------------------------------------------

def test_synonym_expansion_finds_pcr_in_recycled_pet_page(standard_client):
    """Closes EVALUATION.md C4. 'PCR' expands to 'post-consumer recycled' so
    the recycled-PET product page wins over a passing mention in a blog."""
    r = standard_client.get("/api/search", params={"q": "PCR content for PET"})
    body = r.json()
    assert body["no_results"] is False
    assert "recycled PET" in body["results"][0]["title"]


def test_synonym_expansion_finds_bioplastics_via_pla(standard_client):
    """Closes EVALUATION.md D1 vocabulary mismatch. 'bioplastics' expands
    to 'bio-based PLA' so the sustainable-materials roadmap wins."""
    r = standard_client.get("/api/search",
                            params={"q": "why don't we use bioplastics?"})
    body = r.json()
    assert body["no_results"] is False
    assert "sustainable materials" in body["results"][0]["title"].lower()


def test_recency_intent_gates_full_boost(standard_client):
    """Closes EVALUATION.md A5 ranking flip. Vague-intent queries no longer
    have ranking flipped by recency: the partnership content beats the
    fresh supply-chain post."""
    r = standard_client.get(
        "/api/search",
        params={"q": "I want content around why a customer should work with us"},
    )
    body = r.json()
    titles = [c["title"] for c in body["results"]]
    assert any("Why customers choose MJS" in t for t in titles)
    # The partnership content should be at #1, ahead of the supply-chain post.
    idx_part = next(
        (i for i, t in enumerate(titles) if "Why customers choose MJS" in t),
        len(titles),
    )
    idx_supply = next(
        (i for i, t in enumerate(titles) if "Recent supply chain update" in t),
        len(titles),
    )
    assert idx_part < idx_supply


def test_pure_recency_intent_returns_date_sorted_listing(standard_client):
    """Closes EVALUATION.md C2. 'newest content' switches to a date-sorted
    listing rather than relying on accidental token matches."""
    r = standard_client.get("/api/search", params={"q": "newest content"})
    body = r.json()
    assert body["no_results"] is False
    assert body.get("mode") == "recent"
    dates = [c["publish_date"] for c in body["results"] if c["publish_date"]]
    assert dates == sorted(dates, reverse=True)


def test_degenerate_query_returns_no_results(standard_client):
    """Closes EVALUATION.md D5. 'show me everything' has no usable tokens."""
    r = standard_client.get("/api/search", params={"q": "show me everything"})
    body = r.json()
    assert body["no_results"] is True
