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

### Pull a real RSS feed

Sign in as `tom@mjs-packaging.example`, open the **Admin → Ingestion**
panel, paste a feed URL (any public RSS / Atom feed — e.g. a packaging
industry blog), pick a content type, and **Fetch & index**. Entries are
parsed via stdlib XML, chunked, hashed, and merged into the index
alongside the seed content.

## Architecture mapping

| Architecture writeup section            | Prototype implementation                                            |
| --------------------------------------- | ------------------------------------------------------------------- |
| §2 Architecture overview                | `backend/main.py` (Search API), `frontend/` (Web UI)                |
| §3 Per-source workers, change detection | `backend/ingestion.py` — seed loader + RSS loader, SHA-256 hashing  |
| §3 Soft-delete on source removal        | `ingestion.soft_delete_missing`                                     |
| §4 Type-aware chunking                  | `ingestion.chunk_text` (longer for blog/case_study, ts-windows for video/podcast) |
| §4 Hybrid index                         | `backend/search.py` — BM25 + TF-IDF cosine fusion                   |
| §5 Recency boost (bounded)              | `search._recency_multiplier` — exp decay, capped at 1.3×            |
| §5 No-results behaviour                 | `search.Index.search` — three thresholds (weak match, threshold, single-doc signal) |
| §6 Grounding (no LLM in response path)  | The Search API only returns rows from the SQLite index. There is **no LLM in the read path.** |
| §6 Adversarial CI                       | `scripts/eval.py` — fails CI if adversarial queries return content  |
| §7 Entra ID + roles                     | `backend/auth.py` — JWT-shaped tokens, role gate, domain allow-list |
| §7 Admin tag editing without re-scrape  | `PUT /api/admin/documents/{id}/tags` writes to `admin_overrides`, triggers re-index, NOT re-scrape |
| §7 Issue queue                          | `POST /api/issues`, admin queue at `GET /api/admin/issues`          |
| §7 Analytics                            | `queries`, `clicks`, dashboard at `GET /api/admin/analytics`        |

## What is **not** production-grade in this prototype

The architecture writeup describes what changes for a 12-week production
engagement (§9). Concretely, in this prototype:

- **Embeddings:** TF-IDF stand-in, not Azure OpenAI
  `text-embedding-3-large`. TF-IDF was chosen so the demo runs with no
  network, no API key, and no GPU.
- **Search engine:** scikit-learn + `rank-bm25`, not Azure AI Search.
  Therefore no transformer-cross-encoder semantic re-ranker. To
  compensate on this small corpus, the prototype uses score-based
  hybrid fusion (BM25 normalised + cosine, weighted) instead of
  reciprocal rank fusion — the architecture writeup explains the
  production path (§4–§5).
- **Auth:** JWT-shaped HMAC-SHA256 tokens, not real Entra ID OIDC. Token
  shape (`sub`, `email`, `roles`) matches Entra so the swap is
  mechanical (§7).
- **Database:** SQLite, not Postgres. Schema is portable.
- **Push ingestion:** poll-only in the prototype. WebSub for YouTube /
  podcast feeds is the production change (§9).

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
