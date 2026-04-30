# MJS Discovery — working prototype

A runnable prototype of the AI-driven content-discovery system described in
`../architecture.md`. It demonstrates:

- **Ingestion** of a real source channel (configurable RSS feed) plus a
  pre-seeded MJS-shaped corpus, with two-level change detection (HTTP layer
  not exercised in seed mode; SHA-256 normalised body hash always).
- **Natural-language search** returning grounded, ranked results from the
  indexed corpus only — no LLM is in the response path.
- **No-results / hallucination-prevention behaviour** when a query has no
  matching content. Verified by the adversarial queries in
  `scripts/eval.py`.
- **Mobile-first UI** with search, prompting guide, issue-reporting form,
  and an admin panel (tags, issue queue, analytics, ingestion controls).
- **Mocked Entra ID SSO** with two roles (`Standard.User`, `Admin`) and a
  domain allow-list (`@mjs-packaging.example`) — same token shape as
  Entra-issued JWTs, so the swap is mechanical.

## Running locally

Requires Python 3.10+.

```bash
# from the repo root
pip install -r prototype/requirements.txt
python -m uvicorn prototype.backend.main:app --host 127.0.0.1 --port 8765
```

Then open `http://127.0.0.1:8765/`.

On first start the SQLite database is created at
`prototype/data/discovery.sqlite3` and the seed corpus is auto-loaded.

### Demo accounts

| Email                              | Role           |
| ---------------------------------- | -------------- |
| `alice@mjs-packaging.example`      | Standard.User  |
| `tom@mjs-packaging.example`        | Admin          |

Any other domain is rejected at the login endpoint (matches the
production "MJS-only tenant" rule).

### Try these queries

Real queries (should return ranked results):

- `Why should a customer work with us?`
- `What case studies do we have around food-grade packaging?`
- `Do we have any content about sustainable materials?`
- `What have we published recently about supply chain?`
- `pharma-grade glass case studies`
- `airless pump cosmetics`

Adversarial / out-of-corpus queries (should return the no-results state,
not a fabricated answer):

- `What is the population of Tokyo?`
- `Who is the current US president?`
- `Tell me about the Eiffel Tower`
- `How do I bake sourdough bread?`

### Run the golden eval

```bash
python -m prototype.scripts.eval
```

This loads the seed corpus and runs the queries above (real + adversarial)
through the same retrieval code the API uses. Prints a pass/fail per
query and exits non-zero on any failure — suitable for CI.

### Run the full requirement-validation test suite

```bash
pytest tests/
```

The suite under `../tests/` validates the prototype against every
requirement in the brief, organised by category:

| File | Requirement category from the brief |
|---|---|
| `test_auth.py`        | Access Control and Security (SSO, domain restriction, session expiry, sliding-window inactivity) |
| `test_roles.py`       | User Roles (Standard.User vs Admin enforcement) |
| `test_search.py`      | Search and Retrieval (NL search, ranked cards, recency, source-link contract, brief's example queries) |
| `test_grounding.py`   | Grounding and Hallucination Prevention (adversarial queries, prompt-injection attempts, presence-in-index invariant) |
| `test_ingestion.py`   | Ingestion and Indexing (sitemap worker, RSS+VTT, YouTube push, change detection, soft-delete, metadata extraction) |
| `test_scheduler.py`   | ~5-minute freshness target without hammering sources |
| `test_admin.py`       | Admin tooling (tag edits without re-scrape, issue queue, analytics dashboard signals) |
| `test_ux_contract.py` | UX (mobile-first, NL placeholder, no folder navigation, prompting guide, issue form) |
| `test_websub.py`      | YouTube WebSub callback contract (verify handshake + signed delivery) |
| `test_out_of_scope.py`| Asserts the brief's out-of-scope items have not crept in (no synthesis, no shareable links, no PDF, no suppression) |

### Pull a real RSS feed

Sign in as `tom@mjs-packaging.example`, open the **Admin → Ingestion**
panel, paste a feed URL (any public RSS / Atom feed — e.g. a packaging
industry blog), pick a content type, and **Fetch & index**. Entries are
parsed via stdlib XML, chunked, hashed, and merged into the index
alongside the seed content.

## Switching to real Azure AI Search

The prototype defaults to a local TF-IDF + BM25 backend so it can run
offline with no credentials. A pluggable Azure AI Search backend ships
in the same tree (`prototype/backend/azure_search.py`) and can be
switched on with environment variables — no code changes required.

```bash
# Local backend (default) — no env vars needed
uvicorn prototype.backend.main:app

# Azure AI Search backend
export MJS_SEARCH_BACKEND=azure
export AZURE_SEARCH_ENDPOINT=https://<your-service>.search.windows.net
export AZURE_SEARCH_INDEX=mjs-discovery
export AZURE_SEARCH_KEY=<admin-key>          # or use managed identity
export MJS_AZURE_RERANKER_THRESHOLD=1.5      # @search.rerankerScore floor
uvicorn prototype.backend.main:app
```

What flips when `MJS_SEARCH_BACKEND=azure`:

| Path | Local | Azure |
|---|---|---|
| Read | TF-IDF + BM25 + score-based fusion + recency boost | AI Search hybrid (BM25 + vector) → semantic re-rank → freshness scoring profile (capped at 1.3×) |
| No-results gate | bm25/cos thresholds + per-token coverage | top `@search.rerankerScore < 1.5` → no_results |
| Embeddings | none (TF-IDF) | `text-embedding-3-large` (3072d) via AI Search integrated vectorisation |
| Recency | client-side multiplier | scoring profile `recency-boost` (architecture §5) |
| Push on ingest | write SQLite chunks | also POST `mergeOrUpload` batch to AI Search after commit |
| Soft-delete | mark `deleted_at` in SQLite | also POST `delete` batch to AI Search |

What does **not** change:

- Postgres / SQLite is still source-of-truth (architecture §2).
- The Search API response envelope is identical — UI, tests, and the
  `eval.py` / `demo_queries.py` scripts all work without modification.
- Grounding is still architectural: the AI Search semantic re-ranker is
  a transformer cross-encoder, not a generative model. There is still
  no LLM in the read path.
- Attack-pattern detection runs client-side before any AI Search call,
  saving the round-trip on adversarial queries.

### One-time setup against a real AI Search resource

```bash
# 1. Create the index from samples/storage/ai-search-index.json
export AZURE_SEARCH_ENDPOINT=https://<service>.search.windows.net
export AZURE_SEARCH_KEY=<admin-key>
python -c "from prototype.backend import azure_search; \
  print(azure_search.create_or_update_index())"

# 2. Replicate the seed corpus to AI Search
export MJS_SEARCH_BACKEND=azure
python -c "from prototype.backend import db, ingestion; \
  db.init_db(); print(ingestion.ingest_seed())"
```

Production additionally swaps `AZURE_SEARCH_KEY` for managed-identity
auth (architecture §9 — Key Vault + system-assigned identity on the
hosting workload) and adds a paired-region replica.

### Testing without Azure access

`tests/test_azure_backend.py` exercises the full Azure code path
(create-index, push, search, delete, factory wiring, ingestion
replication) using `httpx.MockTransport`. No real Azure account is
needed. Run with:

```bash
pytest tests/test_azure_backend.py
```

## What is **not** production-grade in this prototype

The architecture writeup describes what changes for a 12-week production
engagement (§9). Concretely, in this prototype:

- **Embeddings:** TF-IDF stand-in, not Azure OpenAI
  `text-embedding-3-large`. TF-IDF was chosen so the demo runs with no
  network, no API key, and no GPU.
- **Search engine (default):** scikit-learn + `rank-bm25`, not Azure AI
  Search. Therefore no transformer-cross-encoder semantic re-ranker. To
  compensate on this small corpus, the local backend uses score-based
  hybrid fusion (BM25 normalised + cosine, weighted) instead of
  reciprocal rank fusion — the architecture writeup explains the
  production path (§4–§5).  Setting `MJS_SEARCH_BACKEND=azure` plus
  `AZURE_SEARCH_*` env vars routes the read path to real Azure AI
  Search; see "Switching to real Azure AI Search" above.
- **Auth:** JWT-shaped HMAC-SHA256 tokens, not real Entra ID OIDC. Token
  shape (`sub`, `email`, `roles`) matches Entra so the swap is
  mechanical (§7).
- **Database:** SQLite, not Postgres. Schema is portable.
- **YouTube Data API for caption pulls:** the prototype's WebSub
  endpoint accepts and verifies push notifications and ingests the
  Atom payload's title/URL/published date as a stub video document.
  Production fetches the full description and caption track via the
  YouTube Data API (no API key in the local demo).

## File layout

```
prototype/
├── backend/
│   ├── auth.py        # mock SSO with Entra-shaped tokens, roles
│   ├── db.py          # SQLite schema and connection
│   ├── ingestion.py   # seed loader + RSS loader, chunking, change detection
│   ├── main.py        # FastAPI app: /api/search, /api/admin/*, etc.
│   └── search.py      # hybrid retrieval, recency boost, no-results gates
├── frontend/
│   ├── index.html     # mobile-first single-page UI
│   ├── app.js         # vanilla JS, no framework
│   └── style.css      # responsive, prefers-color-scheme aware
├── data/
│   └── seed.json      # 17 representative MJS items across 5 content types
├── scripts/
│   ├── eval.py        # golden-set + adversarial evaluator
│   └── run.sh         # convenience launcher
├── requirements.txt
└── README.md
```
