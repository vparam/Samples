# Sample dataset and storage

Concrete artifacts for the storage layers described in `../architecture.md`. They show **the shape of the data at each layer** and **how it would be deployed in production** (Postgres + Azure AI Search), independent of the prototype's local SQLite implementation.

## Layout

```
samples/
├── storage/                       Production storage definitions
│   ├── postgres-schema.sql        Metadata, checkpoints, analytics, issue queue
│   ├── ai-search-index.json       Hybrid + semantic + vector index definition
│   └── ai-search-query-template.json  Sample request body for /docs/search
│
├── dataset/                       Sample data shaped exactly as it lands in each store
│   ├── sources.jsonl              Configured source channels (website, podcast, YouTube)
│   ├── documents.jsonl            One row per published item (Postgres documents)
│   ├── chunks.jsonl               Pre-embedding chunks (Postgres chunks)
│   ├── ai-search-payload.jsonl    Same chunks shaped for AI Search /docs/index
│   ├── admin_overrides.jsonl      Admin tag edits (Postgres admin_overrides)
│   ├── queries.jsonl              Sample analytics rows (Postgres queries)
│   ├── clicks.jsonl               Sample click events (Postgres clicks)
│   └── issues.jsonl               Sample issue queue rows (Postgres issues)
│
└── sources/                       Source-side fixtures for the ingestion workers
    ├── sitemap.xml                What the website worker polls
    ├── podcast-feed.xml           What the podcast worker polls (with WebSub hub)
    ├── youtube-websub-callback.xml  What the YouTube WebSub endpoint receives
    ├── blog-page.html             Sample article HTML the website worker scrapes
    └── podcast-transcript.vtt     Sample transcript chunked into ~75s windows
```

## How the layers connect

```
┌─────────────────────┐  HTTP poll / WebSub push  ┌────────────────┐
│ sources/  fixtures  │ ─────────────────────────►│ ingestion       │
│ sitemap.xml         │                           │ worker (per     │
│ podcast-feed.xml    │                           │ source kind)    │
│ youtube-websub..xml │                           └─────┬───────────┘
└─────────────────────┘                                 │
                                                        │ 1. fetch + hash + chunk
                                                        ▼
                                            ┌──────────────────────────┐
                                            │  Postgres                │
                                            │  (postgres-schema.sql)   │
                                            │                          │
                                            │  documents.jsonl  ───────┼──┐
                                            │  chunks.jsonl     ───────┼──┤  2. index
                                            │  admin_overrides ────────┼──┤
                                            │  queries / clicks / issues  │
                                            └──────────────────────────┘  │
                                                                          ▼
                                                          ┌──────────────────────────┐
                                                          │  Azure AI Search         │
                                                          │  (ai-search-index.json)  │
                                                          │                          │
                                                          │  ai-search-payload.jsonl │
                                                          │  (BM25 + vector +        │
                                                          │   semantic re-ranker)    │
                                                          └──────────────────────────┘
```

Postgres is the durable source-of-truth for metadata, ingestion checkpoints, admin edits, and analytics. Azure AI Search holds the retrieval payload (chunk text + embedding vectors + filterable metadata) and runs the BM25 + vector + semantic-rerank pipeline. The two stores stay in sync via the indexer code: a change to a document in Postgres triggers an upsert into AI Search, a soft-delete triggers a `delete` action.

## Mapping to the architecture writeup

| Architecture section | Artifact |
|---|---|
| §3 Per-source workers, polling, WebSub | `sources/sitemap.xml`, `sources/podcast-feed.xml`, `sources/youtube-websub-callback.xml` |
| §3 HTTP-layer change detection (ETag, If-Modified-Since) | `storage/postgres-schema.sql` → `http_cache` table |
| §3 Two-level change detection (SHA-256 of body) | `storage/postgres-schema.sql` → `documents.content_hash` |
| §3 Soft-delete on source removal | `storage/postgres-schema.sql` → `documents.deleted_at`, `idx_documents_alive` partial index |
| §3 Worker checkpoints | `storage/postgres-schema.sql` → `ingestion_runs` table |
| §4 Type-aware chunking (heading-prepended for blog, time-windowed for video/podcast) | `dataset/chunks.jsonl` (note `section_heading` for blog/product, `timestamp_seconds` for podcast/video) |
| §4 Embedding model (`text-embedding-3-large`, 3072 dims) | `storage/ai-search-index.json` → `content_vector` field, `vectorizers.azureOpenAIParameters` |
| §4 Hybrid retrieval (BM25 + vector) | `storage/ai-search-index.json` → searchable `content` + vector field, `storage/ai-search-query-template.json` shows the dual query |
| §4 Semantic re-ranker (L2 cross-encoder) | `storage/ai-search-index.json` → `semantic.configurations.mjs-semantic` |
| §5 Bounded recency boost (cap 1.3×) | `storage/ai-search-index.json` → `scoringProfiles[0]` with `boost: 1.3` and `freshness.boostingDuration: P180D` |
| §5 No-results threshold | `storage/ai-search-query-template.json` → comment block on `@search.rerankerScore` cutoff |
| §7 Entra ID token shape, role gating | `storage/postgres-schema.sql` → `users` table caches token claims; `app_role` enum mirrors the `roles` claim |
| §7 Admin tag edits trigger re-index, not re-scrape | `storage/postgres-schema.sql` → `admin_overrides` separate from `source_tags`; `dataset/admin_overrides.jsonl` shows the resulting rows |
| §7 Audit trail on metadata edits | `storage/postgres-schema.sql` → `admin_overrides_audit` |
| §7 Analytics (queries, zero-results, clicks) | `dataset/queries.jsonl`, `dataset/clicks.jsonl`, plus `v_zero_result_top` / `v_top_queries_7d` views |
| §7 Issue queue | `storage/postgres-schema.sql` → `issues`; `dataset/issues.jsonl` shows queue states |

## Scale and shape notes

- **`documents.jsonl`** carries `source_metadata` as `jsonb`. The shape varies by `content_type` — blog posts carry `author` / `reading_time_minutes`; products carry `sku_family` / `spec_table`; videos carry `video_id` / `chapters` / `caption_track`. This is intentional: per-source workers preserve source-specific signal that a generic crawler would flatten away (architecture §3).
- **`chunks.jsonl`** is the durable, re-emittable form of what AI Search holds. Embeddings are *not* duplicated to Postgres — they live only in AI Search (3072 floats × millions of chunks would be ~12 GB per million chunks). On a re-index, the indexer re-embeds from `chunks.text`.
- **`ai-search-payload.jsonl`** shows the upload shape with `content_vector` truncated for readability. In production each line carries the full 3072-element array; AI Search accepts batches of up to 1000 documents per `/docs/index` call.
- **`http_cache`** is keyed on URL, not on document. Its purpose is to short-circuit the *first* fetch with a 304 before any parsing or hashing happens (architecture §3).

## Loading the sample data

The prototype's auto-seed (`prototype/data/seed.json`) is the SQLite-shaped equivalent of `dataset/documents.jsonl`. To load this richer dataset into Postgres:

```bash
psql "$DATABASE_URL" -f samples/storage/postgres-schema.sql

# Sources first (parents of documents)
psql "$DATABASE_URL" -c "\copy sources FROM PROGRAM 'jq -c . samples/dataset/sources.jsonl' WITH (FORMAT csv)"
# ...etc. In practice this is done via the ingestion workers; the JSONL
# files are intended as fixtures for tests and as a clear reference for
# what each storage layer holds.
```

To create the AI Search index:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "api-key: $SEARCH_ADMIN_KEY" \
  --data @samples/storage/ai-search-index.json \
  "https://$SEARCH_SERVICE.search.windows.net/indexes?api-version=2024-07-01"
```

## What this is **not**

These files are *fixtures and reference shapes*. They are not a runtime: the ingestion workers, indexer, and Search API code that produce and consume them live elsewhere (and the `prototype/` tree is a single-process SQLite stand-in that exercises the same shapes end-to-end).
