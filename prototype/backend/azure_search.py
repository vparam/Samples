"""Azure AI Search backend.

Switched on by environment:

  MJS_SEARCH_BACKEND=azure
  AZURE_SEARCH_ENDPOINT=https://<service>.search.windows.net
  AZURE_SEARCH_INDEX=mjs-discovery
  AZURE_SEARCH_KEY=<admin or query key>
    (in production: managed identity instead — see azure_credential())

The index schema is in samples/storage/ai-search-index.json. Push it once
with `python -m prototype.backend.azure_search create-index` (or via the
Azure CLI / portal). The schema declares:
  - `content` BM25-searchable
  - `content_vector` (3072 dims) with integrated AOAI vectorisation
  - semantic config `mjs-semantic` driving the L2 cross-encoder reranker
  - scoring profile `recency-boost` with the bounded freshness function
    (architecture §5)

This module:
  - implements the same {load, search, is_empty} surface as the local
    backend so prototype/backend/search.py:get_index() can swap freely
  - exposes push_document() called by ingestion.upsert_item when Azure
    is active — re-index on change, no double-storage of vectors
  - never embeds in our process: AI Search calls AOAI for us via
    integrated vectorisation. There is no LLM in the read path either —
    the semantic ranker is a cross-encoder, not a generative model
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from . import db
from .search import (  # reuse the client-side gates and helpers
    _has_recency_intent,
    _is_pure_recency_intent,
    _looks_like_attack,
)

log = logging.getLogger("mjs.azure_search")

API_VERSION = "2024-07-01"

# Threshold for AI Search's @search.rerankerScore (0..4 scale, 4 = perfect).
# Tuned in production against the golden eval set (architecture §8).
RERANKER_THRESHOLD = float(os.environ.get("MJS_AZURE_RERANKER_THRESHOLD", "1.5"))


def _config() -> dict[str, str] | None:
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    index = os.environ.get("AZURE_SEARCH_INDEX", "mjs-discovery")
    key = os.environ.get("AZURE_SEARCH_KEY")
    if not (endpoint and key):
        return None
    return {"endpoint": endpoint.rstrip("/"), "index": index, "key": key}


def is_configured() -> bool:
    return _config() is not None


def _client() -> httpx.Client:
    cfg = _config()
    if not cfg:
        raise RuntimeError(
            "AzureIndex selected but AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_KEY "
            "are not set. See prototype/README.md for setup."
        )
    transport = _TEST_TRANSPORT  # injected by tests via set_test_transport()
    kwargs = {"timeout": 15.0, "headers": {
        "api-key": cfg["key"], "Content-Type": "application/json"}}
    if transport is not None:
        kwargs["transport"] = transport
    return httpx.Client(**kwargs)


# Tests inject a MockTransport so this whole module is exercisable
# without real Azure credentials. Production: leave as None.
_TEST_TRANSPORT: httpx.BaseTransport | None = None


def set_test_transport(t: httpx.BaseTransport | None) -> None:
    global _TEST_TRANSPORT
    _TEST_TRANSPORT = t


# -----------------------------------------------------------------------------
# Index management
# -----------------------------------------------------------------------------

INDEX_SCHEMA_PATH = (
    # samples/ lives at the repo root, two levels up from this file
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "samples" / "storage" / "ai-search-index.json"
)


def create_or_update_index() -> dict:
    cfg = _config()
    if not cfg:
        raise RuntimeError("Azure not configured")
    schema = json.loads(INDEX_SCHEMA_PATH.read_text())
    # The samples schema embeds editorial _comment fields for humans;
    # AI Search rejects those.
    schema = _strip_comments(schema)
    schema["name"] = cfg["index"]
    url = f"{cfg['endpoint']}/indexes/{cfg['index']}?api-version={API_VERSION}"
    with _client() as c:
        r = c.put(url, json=schema)
    r.raise_for_status()
    return r.json()


def _strip_comments(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items()
                if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_comments(x) for x in obj]
    return obj


# -----------------------------------------------------------------------------
# Push / delete
# -----------------------------------------------------------------------------

def _doc_to_payload(doc_row: dict, chunk_rows: list[dict],
                    source_tags: list[str], admin_tags: list[str]
                    ) -> list[dict]:
    """One AI Search document per chunk. content_vector omitted from the
    upload — the index's `mjs-vectorizer-aoai` integrated vectoriser
    populates it on ingest."""
    out = []
    tags = sorted(set(source_tags + admin_tags))
    pub = doc_row["publish_date"]
    if pub and len(pub) == 10:
        pub = pub + "T00:00:00Z"
    for ch in chunk_rows:
        out.append({
            "@search.action": "mergeOrUpload",
            "id": f"{doc_row['id']}-{ch['chunk_index']:04d}",
            "document_id": str(doc_row["id"]),
            "chunk_index": ch["chunk_index"],
            "content": ch["text"],
            "section_heading": ch.get("section_heading") or "",
            "title": doc_row["title"],
            "source_url": doc_row["source_url"],
            "content_type": doc_row["content_type"],
            "publish_date": pub,
            "tags": tags,
            "timestamp_seconds": ch.get("timestamp_seconds"),
        })
    return out


def push_document(document_id: int) -> dict:
    """Push every chunk of a document to AI Search. Idempotent
    (mergeOrUpload). Called by ingestion.upsert_item when active."""
    cfg = _config()
    if not cfg:
        return {"skipped": "azure_not_configured"}
    with db.connect() as cx:
        doc = cx.execute(
            "SELECT id, source_url, content_type, title, publish_date, deleted_at "
            "FROM documents WHERE id = ?", (document_id,),
        ).fetchone()
        if not doc:
            return {"skipped": "doc_not_found"}
        if doc["deleted_at"]:
            return delete_document(document_id)
        chunks = cx.execute(
            "SELECT chunk_index, text, timestamp_seconds FROM chunks "
            "WHERE document_id = ? ORDER BY chunk_index", (document_id,),
        ).fetchall()
        st = cx.execute(
            "SELECT tags FROM source_tags WHERE document_id = ?", (document_id,),
        ).fetchone()
        ot = cx.execute(
            "SELECT tags FROM admin_overrides WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    payload = _doc_to_payload(
        dict(doc), [dict(c) for c in chunks],
        json.loads(st["tags"]) if st else [],
        json.loads(ot["tags"]) if ot else [],
    )
    return _post_index_batch(payload)


def delete_document(document_id: int) -> dict:
    """Remove every chunk of `document_id` from AI Search. Used on
    soft-delete reconciliation (architecture §3)."""
    cfg = _config()
    if not cfg:
        return {"skipped": "azure_not_configured"}
    # Without a /docs/index range delete, we issue an explicit batch.
    with db.connect() as cx:
        rows = cx.execute(
            "SELECT chunk_index FROM chunks WHERE document_id = ?",
            (document_id,),
        ).fetchall()
    payload = [
        {"@search.action": "delete",
         "id": f"{document_id}-{r['chunk_index']:04d}"}
        for r in rows
    ]
    return _post_index_batch(payload) if payload else {"skipped": "no_chunks"}


def _post_index_batch(actions: list[dict]) -> dict:
    cfg = _config()
    if not actions or not cfg:
        return {"skipped": "no_actions"}
    url = f"{cfg['endpoint']}/indexes/{cfg['index']}/docs/index?api-version={API_VERSION}"
    with _client() as c:
        # Batches up to 1000 per call (AI Search limit).
        for i in range(0, len(actions), 1000):
            batch = actions[i : i + 1000]
            r = c.post(url, json={"value": batch})
            r.raise_for_status()
    return {"pushed": len(actions)}


# -----------------------------------------------------------------------------
# Read path: hybrid + semantic re-rank, no LLM
# -----------------------------------------------------------------------------

class AzureIndex:
    """Search backend that routes to Azure AI Search.

    Same response envelope as LocalIndex.search() so callers don't care
    which backend is active. Crucially, no generative model is involved
    in the read path — AI Search's semantic re-ranker is a cross-encoder.
    """

    def __init__(self) -> None:
        cfg = _config()
        if cfg is None:
            raise RuntimeError("AzureIndex requires AZURE_SEARCH_* env vars")
        self.cfg = cfg

    def load(self) -> None:
        return None  # state lives server-side

    def is_empty(self) -> bool:
        # /docs/$count returns "0" or a number as a string.
        url = (f"{self.cfg['endpoint']}/indexes/{self.cfg['index']}/docs/"
               f"$count?api-version={API_VERSION}")
        with _client() as c:
            try:
                r = c.get(url)
                r.raise_for_status()
                return int(r.text.strip()) == 0
            except Exception:
                return False  # don't break boot on a transient failure

    def search(self, query: str, k: int = 10) -> dict:
        # Client-side gates that should never reach Azure (cheap rejects).
        if _looks_like_attack(query):
            return {"results": [], "no_results": True, "reason": "attack_pattern"}
        if _is_pure_recency_intent(query):
            return self._listing_by_date(k)

        body = self._build_search_body(query, k)
        url = (f"{self.cfg['endpoint']}/indexes/{self.cfg['index']}/docs/"
               f"search?api-version={API_VERSION}")
        with _client() as c:
            r = c.post(url, json=body)
        r.raise_for_status()
        data = r.json()
        return self._shape_results(data, k)

    # -- helpers ----------------------------------------------------------

    def _build_search_body(self, query: str, k: int) -> dict:
        # Recency-intent gating: we let the index's scoring profile
        # apply the bounded freshness function only when the query
        # carries recency intent. The same profile is configured with
        # `boost: 1.3` capped so it can never override relevance.
        scoring_profile = "recency-boost" if _has_recency_intent(query) else None
        body = {
            "search": query,
            "queryType": "semantic",
            "semanticConfiguration": "mjs-semantic",
            "queryLanguage": "en-us",
            "captions": "extractive|highlight-true",
            "answers": "none",
            "top": max(k * 2, 20),  # over-fetch so doc-rollup leaves k full
            "vectorQueries": [{
                "kind": "text", "text": query,
                "fields": "content_vector", "k": 50,
            }],
            "select": ("document_id,title,content_type,publish_date,"
                       "source_url,tags,timestamp_seconds,content,chunk_index"),
            "highlightFields": "content",
        }
        if scoring_profile:
            body["scoringProfile"] = scoring_profile
        return body

    def _shape_results(self, data: dict, k: int) -> dict:
        rows = data.get("value", [])
        if not rows:
            return {"results": [], "no_results": True, "reason": "no_match"}
        # Architecture §5 no-results threshold: top reranker score must
        # clear RERANKER_THRESHOLD (default 1.5 / 4.0).
        top_reranker = float(rows[0].get("@search.rerankerScore", 0.0) or 0.0)
        if top_reranker < RERANKER_THRESHOLD:
            return {"results": [], "no_results": True,
                    "reason": "below_threshold"}

        # Roll chunk hits up to documents — best chunk wins.
        seen: dict[str, dict] = {}
        for r in rows:
            doc_id = r.get("document_id") or r.get("id")
            if doc_id in seen:
                continue
            seen[doc_id] = r
            if len(seen) >= k:
                break

        results = []
        for r in seen.values():
            url = r.get("source_url", "")
            ts = r.get("timestamp_seconds")
            if ts is not None and "youtube.com" in url:
                url = f"{url}&t={ts}"
            excerpt = r.get("content", "")
            captions = r.get("@search.captions") or []
            if captions:
                excerpt = captions[0].get("highlights") or captions[0].get("text") or excerpt
            results.append({
                "document_id": r.get("document_id"),
                "title": r.get("title"),
                "content_type": r.get("content_type"),
                "publish_date": (r.get("publish_date") or "")[:10] or None,
                "url": url,
                "excerpt": excerpt[:280] + ("…" if len(excerpt) > 280 else ""),
                "tags": r.get("tags") or [],
                "score": round(float(r.get("@search.rerankerScore") or 0.0), 4),
                "recency_boost": round(
                    float(r.get("@search.score") or 0.0)
                    / max(top_reranker, 0.01), 3,
                ),
            })
        return {"results": results, "no_results": False}

    def _listing_by_date(self, k: int) -> dict:
        """Pure-recency intent fallback: an OData orderby on publish_date."""
        url = (f"{self.cfg['endpoint']}/indexes/{self.cfg['index']}/docs/"
               f"search?api-version={API_VERSION}")
        body = {
            "search": "*",
            "orderby": "publish_date desc",
            "top": k,
            "select": ("document_id,title,content_type,publish_date,"
                       "source_url,tags,content"),
        }
        with _client() as c:
            r = c.post(url, json=body)
        r.raise_for_status()
        rows = r.json().get("value", [])
        seen: dict[str, dict] = {}
        for r in rows:
            doc_id = r.get("document_id") or r.get("id")
            if doc_id not in seen:
                seen[doc_id] = r
        results = []
        for r in list(seen.values())[:k]:
            txt = r.get("content") or r.get("title") or ""
            results.append({
                "document_id": r.get("document_id"),
                "title": r.get("title"),
                "content_type": r.get("content_type"),
                "publish_date": (r.get("publish_date") or "")[:10] or None,
                "url": r.get("source_url"),
                "excerpt": txt[:240] + ("…" if len(txt) > 240 else ""),
                "tags": r.get("tags") or [],
                "score": 1.0, "recency_boost": 1.0,
            })
        return {"results": results, "no_results": False, "mode": "recent"}
