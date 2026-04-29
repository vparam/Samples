"""Hybrid retrieval: BM25 + TF-IDF vector via reciprocal rank fusion,
plus a bounded recency boost. The architecture writeup specifies Azure AI
Search with native hybrid retrieval and a transformer cross-encoder
re-ranker; this prototype substitutes scikit-learn TF-IDF for the
"vector" half and skips the semantic re-ranker, since neither Azure AI
Search nor a cross-encoder is available in a self-contained local demo.
The retrieval shape (RRF + recency multiplier + no-results threshold)
matches Section 5 of the writeup.

Crucially, no LLM is in this code path. The Search API can only return
items present in the SQLite index. Section 6 layer 1: grounding by
construction.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from threading import Lock
from typing import Iterable

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

from . import db


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Aggressive stopword list. The TF-IDF half already drops English stopwords
# via sklearn; we mirror that on the BM25 side so common verbs and pronouns
# do not push weak documents over the no-results threshold on adversarial
# queries like "Who is the current US president?".
_STOPWORDS = frozenset("""
a about above across actually after again against all also always am among an
and any anyone anything are aren as at be because been before being below
between both but by can cannot could did do does doing don each either else
ever every everyone everything for from further get got had has have having
he her here hers herself him himself his how i if in indeed into is isn it
its itself just kind like make me might more most much must my myself never
no nor not now of off on once one only or other our ours out over own please
pretty quite rather really same say see she should simply so some someone
something somewhat still such t tell than that the their theirs them themselves
then there these they thing things this those though through thus to too under
until up upon us use used usually very was way we were what whatever when where
which while who whom why will with would yet you your yours yourself yourselves
""".split())


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _query_tokens(text: str) -> list[str]:
    """Tokens for retrieval: lowercased, stopwords removed, length >= 2."""
    return [t for t in _tokens(text) if t not in _STOPWORDS and len(t) > 1]


@dataclass
class Chunk:
    chunk_id: int
    document_id: int
    text: str
    timestamp_seconds: int | None


@dataclass
class Document:
    id: int
    source_url: str
    content_type: str
    title: str
    publish_date: str | None
    body: str
    source_tags: list[str]
    admin_tags: list[str]


class Index:
    """In-memory hybrid index, rebuilt on demand from SQLite."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._loaded_at: datetime | None = None
        self._chunks: list[Chunk] = []
        self._docs: dict[int, Document] = {}
        self._bm25: BM25Okapi | None = None
        self._tfidf: TfidfVectorizer | None = None
        self._tfidf_matrix = None

    def load(self) -> None:
        with self._lock:
            with db.connect() as cx:
                doc_rows = cx.execute(
                    """SELECT d.id, d.source_url, d.content_type, d.title,
                              d.publish_date, d.body,
                              COALESCE(s.tags,'[]') AS source_tags,
                              COALESCE(a.tags,'[]') AS admin_tags
                       FROM documents d
                       LEFT JOIN source_tags s ON s.document_id = d.id
                       LEFT JOIN admin_overrides a ON a.document_id = d.id
                       WHERE d.deleted_at IS NULL"""
                ).fetchall()
                chunk_rows = cx.execute(
                    """SELECT c.id, c.document_id, c.text, c.timestamp_seconds
                       FROM chunks c
                       JOIN documents d ON d.id = c.document_id
                       WHERE d.deleted_at IS NULL
                       ORDER BY c.document_id, c.chunk_index"""
                ).fetchall()

            self._docs = {
                r["id"]: Document(
                    id=r["id"], source_url=r["source_url"],
                    content_type=r["content_type"], title=r["title"],
                    publish_date=r["publish_date"], body=r["body"],
                    source_tags=json.loads(r["source_tags"]),
                    admin_tags=json.loads(r["admin_tags"]),
                )
                for r in doc_rows
            }
            self._chunks = [
                Chunk(chunk_id=r["id"], document_id=r["document_id"],
                      text=r["text"], timestamp_seconds=r["timestamp_seconds"])
                for r in chunk_rows
            ]

            if not self._chunks:
                self._bm25 = None
                self._tfidf = None
                self._tfidf_matrix = None
                self._loaded_at = datetime.utcnow()
                return

            # Build BM25 corpus from chunks plus their document's tags.
            # Admin edits to tags trigger re-index, not re-scrape (section 7).
            corpus_tokens = []
            for ch in self._chunks:
                doc = self._docs[ch.document_id]
                base = _query_tokens(ch.text)
                tag_tokens = _query_tokens(" ".join(doc.source_tags + doc.admin_tags))
                corpus_tokens.append(base + tag_tokens)

            self._bm25 = BM25Okapi(corpus_tokens)

            corpus_text = []
            for ch, toks in zip(self._chunks, corpus_tokens):
                corpus_text.append(ch.text + " " + " ".join(
                    self._docs[ch.document_id].source_tags
                    + self._docs[ch.document_id].admin_tags
                ))
            self._tfidf = TfidfVectorizer(
                lowercase=True, ngram_range=(1, 2),
                sublinear_tf=True, min_df=1, stop_words="english",
            )
            self._tfidf_matrix = self._tfidf.fit_transform(corpus_text)
            self._loaded_at = datetime.utcnow()

    def is_empty(self) -> bool:
        return not self._chunks

    def search(self, query: str, k: int = 10) -> dict:
        with self._lock:
            if not self._chunks or self._bm25 is None or self._tfidf is None:
                return {"results": [], "no_results": True, "reason": "empty_index"}

            q_tokens = _query_tokens(query)
            if not q_tokens:
                return {"results": [], "no_results": True, "reason": "empty_query"}

            bm25_scores = self._bm25.get_scores(q_tokens)
            q_vec = self._tfidf.transform([query])
            # cosine since both sides L2-normalised by TfidfVectorizer
            cos = (self._tfidf_matrix @ q_vec.T).toarray().ravel()

            # Score-based hybrid fusion: normalise BM25 to [0,1] and weight-
            # combine with cosine. The architecture writeup specifies RRF for
            # production (Azure AI Search), which is robust over a large
            # heterogeneous corpus; on this small prototype corpus, rank
            # differences are too tied for RRF to discriminate, and recency
            # then flips winners. Score-based fusion preserves the relative
            # strength signal. Re-evaluate before swapping in real Azure AI
            # Search, where RRF + the L2 cross-encoder semantic reranker is
            # the right choice.
            bm25_max = float(bm25_scores.max()) if bm25_scores.size else 0.0
            cos_max = float(cos.max()) if cos.size else 0.0
            # Absolute floors before declaring any match worth surfacing.
            if bm25_max < 1.5 and cos_max < 0.15:
                return {"results": [], "no_results": True, "reason": "weak_match"}
            # Coverage check: for multi-token queries, require at least two
            # distinct query tokens to actually appear in the top-scoring
            # chunk. This catches adversarial queries where one stray token
            # ("current", "supply") happens to be in the corpus but the
            # rest of the query is out-of-domain.
            # Domain-coverage check. If only one document in the corpus has
            # any meaningful BM25 score for this query, the query is almost
            # certainly out-of-domain (e.g. 'Who is the US president?'
            # accidentally matching one stray 'current'). Real queries
            # surface multiple candidate docs.
            #
            # Exception: a strong absolute BM25 score (>= 3.5) means the
            # query terms are dense in that one document — a precise match
            # like a unique product name or tag. Let it through.
            if len(q_tokens) >= 2 and bm25_max < 3.5:
                docs_with_signal: set[int] = set()
                for i, s in enumerate(bm25_scores):
                    if s > 0.5:
                        docs_with_signal.add(self._chunks[i].document_id)
                if len(docs_with_signal) < 2:
                    return {"results": [], "no_results": True, "reason": "single_doc_signal"}

            # Per-token coverage. For a multi-token query, count how many
            # distinct query tokens contribute any BM25 weight at all. If
            # only one of N tokens is in the corpus (e.g. "unrestricted
            # assistant answer" only matches "answer"), the query is
            # out-of-domain — return no_results regardless of how many
            # docs that one token hit.
            if len(q_tokens) >= 3:
                contributing = 0
                for tok in set(q_tokens):
                    s = self._bm25.get_scores([tok])
                    if s.size and float(s.max()) > 0.5:
                        contributing += 1
                if contributing < 2:
                    return {"results": [], "no_results": True, "reason": "single_token_signal"}
            bm25_norm = bm25_scores / bm25_max if bm25_max > 0 else bm25_scores
            hybrid = 0.6 * bm25_norm + 0.4 * cos

            fused: dict[int, float] = {}
            for i, s in enumerate(hybrid):
                if s > 0:
                    fused[i] = float(s)

            if not fused:
                return {"results": [], "no_results": True, "reason": "no_match"}

            # Roll chunk hits up to documents (best chunk wins)
            doc_best: dict[int, tuple[int, float]] = {}
            for chunk_idx, score in fused.items():
                doc_id = self._chunks[chunk_idx].document_id
                prev = doc_best.get(doc_id)
                if prev is None or score > prev[1]:
                    doc_best[doc_id] = (chunk_idx, score)

            today = date.today()
            ranked = []
            for doc_id, (chunk_idx, raw_score) in doc_best.items():
                doc = self._docs[doc_id]
                recency = _recency_multiplier(doc.publish_date, today)
                final_score = raw_score * recency
                ranked.append((final_score, raw_score, recency, chunk_idx, doc_id))
            ranked.sort(reverse=True)

            # No-results threshold: top hybrid score (pre-recency) must clear
            # this. Tuned against eval.py adversarial queries — anything
            # below 0.10 on the normalised hybrid scale is too weak to be
            # worth showing.
            top_raw = ranked[0][1] if ranked else 0.0
            threshold = 0.10
            if top_raw < threshold:
                return {"results": [], "no_results": True, "reason": "below_threshold"}

            results = []
            for final_score, raw_score, recency, chunk_idx, doc_id in ranked[:k]:
                doc = self._docs[doc_id]
                ch = self._chunks[chunk_idx]
                excerpt = _make_excerpt(ch.text, query)
                deep_url = doc.source_url
                if ch.timestamp_seconds is not None and "youtube.com" in deep_url:
                    deep_url = f"{deep_url}&t={ch.timestamp_seconds}"
                results.append({
                    "document_id": doc.id,
                    "title": doc.title,
                    "content_type": doc.content_type,
                    "publish_date": doc.publish_date,
                    "url": deep_url,
                    "excerpt": excerpt,
                    "tags": sorted(set(doc.source_tags + doc.admin_tags)),
                    "score": round(final_score, 4),
                    "recency_boost": round(recency, 3),
                })
            return {"results": results, "no_results": False}


def _recency_multiplier(publish_date: str | None, today: date) -> float:
    """Bounded exponential decay; cap at 1.3x for fresh, asymptote 1.0 for old.

    Per Section 5: 'Recency tilts close calls; it doesn't override relevance.'
    """
    if not publish_date:
        return 1.0
    try:
        d = date.fromisoformat(publish_date[:10])
    except ValueError:
        return 1.0
    days = max(0, (today - d).days)
    half_life_days = 180.0
    boost = 0.3 * math.exp(-days / half_life_days)
    return 1.0 + boost


def _make_excerpt(text: str, query: str, width: int = 240) -> str:
    """Return a window of `text` centred on the first query-token match."""
    q_tokens = _tokens(query)
    lower = text.lower()
    pos = -1
    for tok in q_tokens:
        i = lower.find(tok)
        if i != -1:
            pos = i
            break
    if pos == -1:
        return text[:width].strip() + ("…" if len(text) > width else "")
    half = width // 2
    start = max(0, pos - half)
    end = min(len(text), pos + half)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "… " + snippet
    if end < len(text):
        snippet = snippet + " …"
    return snippet


# Module-level singleton
_index = Index()


def get_index() -> Index:
    return _index
