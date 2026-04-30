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
