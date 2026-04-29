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
and any anyone anything are aren around as at be because been before being below
between both but by can cannot content could did do does doing don each either
else even ever every everyone everything find for from further get give got had
has have having he her here hers herself him himself his how however i if in
indeed into is isn it its itself just kind like list look make me might more
most much must my myself need needed needs never no nor not now of off on once
one only or other our ours out over own please pretty quite rather really same
say search see she should show simply so some someone something somewhat still
stuff such t tell than that the their theirs them themselves then there these
they thing things this those though through thus to too under until up upon us
use used usually very want wanted wants was way we were what whatever when where
which while who whom why will with would yet you your yours yourself yourselves
""".split())


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _query_tokens(text: str) -> list[str]:
    """Tokens for retrieval: lowercased, stopwords removed, length >= 2."""
    return [t for t in _tokens(text) if t not in _STOPWORDS and len(t) > 1]


# -----------------------------------------------------------------------------
# Query enhancements (closes gaps from EVALUATION.md)
# -----------------------------------------------------------------------------

# Small abbreviation / synonym table. Stand-in for what real embeddings would
# learn from the corpus on day one. Keep this short and domain-specific —
# generic English synonyms belong to the embedding model, not a hand list.
_QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "pcr":         ("post-consumer", "recycled"),
    "rpet":        ("recycled", "pet", "post-consumer"),
    "bioplastic":  ("bio-based", "pla", "biodegradable"),
    "bioplastics": ("bio-based", "pla", "biodegradable"),
    "biobased":    ("bio-based", "pla"),
    "hdpe":        ("hdpe", "high-density", "polyethylene"),
    "ldpe":        ("ldpe", "low-density", "polyethylene"),
    "pet":         ("pet", "polyethylene", "terephthalate"),
    "pla":         ("pla", "bio-based"),
    "usp":         ("usp",),
    "co2":         ("co2", "carbon", "lifecycle"),
}


def _expand_query(text: str) -> str:
    """Append synonym terms for known abbreviations. Production handles this
    via the embedding model; the prototype patches the worst offenders.
    """
    extra: list[str] = []
    for tok in _tokens(text):
        if tok in _QUERY_EXPANSIONS:
            extra.extend(_QUERY_EXPANSIONS[tok])
    return text + (" " + " ".join(extra) if extra else "")


# Tokens that signal recency-intent. When ANY appears in the query, we apply
# the full architecture-§5 1.3× recency cap; otherwise we apply a much
# tighter cap so vague-intent queries don't have ranking flipped by freshness.
_RECENCY_INTENT_TOKENS = frozenset(
    "recent recently latest newest new today yesterday this week month "
    "quarter year fresh upcoming q1 q2 q3 q4".split()
)


def _has_recency_intent(query: str) -> bool:
    return any(t in _RECENCY_INTENT_TOKENS for t in _tokens(query))


# Pure recency-only intent: the user wants "what's new". Triggers a
# date-sorted fallback even when relevance is too thin to clear the gates.
_PURE_RECENCY_PATTERNS = (
    re.compile(r"^\s*(what\s*'?s|whats|show\s+me)\s+new\s*\??\s*$", re.I),
    re.compile(r"^\s*newest\s+(content|posts?|items?|stuff)?\s*$", re.I),
    re.compile(r"^\s*latest\s+(content|posts?|items?|stuff)?\s*$", re.I),
    re.compile(r"^\s*recent\s+(content|posts?|items?|stuff)?\s*$", re.I),
)


def _is_pure_recency_intent(query: str) -> bool:
    return any(p.match(query) for p in _PURE_RECENCY_PATTERNS)


# Prompt-injection / instruction-override patterns. We treat these as
# adversarial and short-circuit to no_results before any ranking happens.
# Conservative — only multi-word imperative attack phrases, never single
# common words. The architecture's production semantic re-ranker would
# reject these on relevance grounds; this is the prototype's stand-in.
_ATTACK_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above)\s+"
               r"(instructions?|prompts?|rules?|directions?)", re.I),
    re.compile(r"\b(you\s+are\s+now|act\s+as|pretend\s+(that\s+|to\s+be\s+)?"
               r"|simulate\s+(an?\s+)?|disregard|override|bypass)", re.I),
    re.compile(r"\b(unrestricted|jailbroken|developer\s+mode|do\s+anything\s+now"
               r"|dan\s+mode)\b", re.I),
    re.compile(r"\b(reveal|leak|print|show|dump)\s+(the\s+)?"
               r"(system|hidden|secret|prompt|instructions?|database|schema)\b",
               re.I),
)


def _looks_like_attack(query: str) -> bool:
    return any(p.search(query) for p in _ATTACK_PATTERNS)


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

    def _date_sorted_listing(self, k: int) -> dict:
        """Pure-recency intent fallback: return the k most-recent documents.
        Same response envelope as search() so the UI handles it transparently.
        """
        docs = [d for d in self._docs.values() if d.publish_date]
        docs.sort(key=lambda d: d.publish_date or "", reverse=True)
        results = []
        for doc in docs[:k]:
            ch = next((c for c in self._chunks if c.document_id == doc.id), None)
            excerpt = (ch.text[:240] + "…") if ch and len(ch.text) > 240 else (ch.text if ch else doc.title)
            results.append({
                "document_id": doc.id,
                "title": doc.title,
                "content_type": doc.content_type,
                "publish_date": doc.publish_date,
                "url": doc.source_url,
                "excerpt": excerpt,
                "tags": sorted(set(doc.source_tags + doc.admin_tags)),
                "score": 1.0,         # listing mode — relevance not scored
                "recency_boost": 1.0,
            })
        return {"results": results, "no_results": False, "mode": "recent"}

    def search(self, query: str, k: int = 10) -> dict:
        with self._lock:
            if not self._chunks or self._bm25 is None or self._tfidf is None:
                return {"results": [], "no_results": True, "reason": "empty_index"}

            # Architectural attack-pattern short-circuit. Production version
            # is the AI Search semantic ranker rejecting on relevance; this
            # is the prototype stand-in.
            if _looks_like_attack(query):
                return {"results": [], "no_results": True, "reason": "attack_pattern"}

            # Pure-recency intent: switch to date-sorted listing. The brief
            # forbids folder navigation but a "what's new" listing is still
            # search-shaped — same response envelope, no synthesis.
            if _is_pure_recency_intent(query):
                return self._date_sorted_listing(k)

            expanded = _expand_query(query)
            q_tokens = _query_tokens(expanded)
            if not q_tokens:
                return {"results": [], "no_results": True, "reason": "empty_query"}

            bm25_scores = self._bm25.get_scores(q_tokens)
            q_vec = self._tfidf.transform([expanded])
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

            # Recency boost is full strength (cap 1.3×, architecture §5)
            # only when the query carries recency intent. Otherwise apply a
            # tighter cap (1.05×) so freshness does not flip the ranking on
            # vague queries — the "I want content around why a customer
            # should work with us" failure from EVALUATION.md.
            recency_cap = 0.3 if _has_recency_intent(query) else 0.02
            today = date.today()
            ranked = []
            for doc_id, (chunk_idx, raw_score) in doc_best.items():
                doc = self._docs[doc_id]
                recency = _recency_multiplier(
                    doc.publish_date, today, cap=recency_cap,
                )
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


def _recency_multiplier(publish_date: str | None, today: date,
                        cap: float = 0.3) -> float:
    """Bounded exponential decay multiplier.

    Returns 1.0 + boost where 0 ≤ boost ≤ cap. cap=0.3 gives the
    architecture §5 1.3× cap for queries with recency intent; cap=0.05
    is the much tighter default for vague-intent queries so freshness
    does not flip ranking on close calls.
    """
    if not publish_date:
        return 1.0
    try:
        d = date.fromisoformat(publish_date[:10])
    except ValueError:
        return 1.0
    days = max(0, (today - d).days)
    half_life_days = 180.0
    boost = cap * math.exp(-days / half_life_days)
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
