-- =============================================================================
-- MJS Discovery — production Postgres schema
--
-- This is the metadata, checkpoint, and analytics store. The retrieval index
-- itself lives in Azure AI Search (see ai-search-index.json); Postgres is the
-- source-of-truth that the index is built from, plus the analytics sink and
-- the issue/admin queue.
--
-- Maps to architecture sections:
--   §3 — ingestion checkpoints, change detection, soft-delete
--   §4 — chunks (pre-embedding) and the embedding payload sent to AI Search
--   §7 — admin_overrides, queries, clicks, issues
--
-- Run order: extensions → enums → tables → indexes → policies.
-- =============================================================================

-- -- Extensions -----------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive emails
CREATE EXTENSION IF NOT EXISTS "btree_gin";  -- composite indexes on jsonb tags

-- -- Enums ----------------------------------------------------------------------
CREATE TYPE content_type AS ENUM (
    'blog', 'case_study', 'product', 'podcast', 'video'
);

CREATE TYPE source_kind AS ENUM (
    'website_sitemap', 'podcast_rss', 'youtube_websub'
);

CREATE TYPE issue_kind AS ENUM (
    'broken_link', 'wrong_result', 'missing_content', 'other'
);

CREATE TYPE issue_status AS ENUM (
    'open', 'in_progress', 'resolved', 'wont_fix'
);

CREATE TYPE app_role AS ENUM (
    'Standard.User', 'Admin'
);

-- =============================================================================
-- Sources & ingestion (architecture §3)
-- =============================================================================

-- One row per configured source channel.
CREATE TABLE sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            source_kind NOT NULL,
    -- For website_sitemap: the sitemap URL.
    -- For podcast_rss:   the feed URL.
    -- For youtube_websub: the channel feed URL (PubSubHubbub topic).
    feed_url        TEXT NOT NULL UNIQUE,
    -- Default content_type for items from this source. May be overridden
    -- per-item where the source carries richer typing.
    default_content_type content_type NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    poll_interval_seconds INT NOT NULL DEFAULT 300, -- 5 min, §3
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HTTP-layer cache so we can skip re-downloading unchanged feeds/pages.
CREATE TABLE http_cache (
    url             TEXT PRIMARY KEY,
    etag            TEXT,
    last_modified   TEXT,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_status     INT
);

-- Worker checkpoints. Crash-mid-run safety from §3.
CREATE TABLE ingestion_runs (
    id              BIGSERIAL PRIMARY KEY,
    source_id       UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    -- 'running' | 'succeeded' | 'failed'
    status          TEXT NOT NULL DEFAULT 'running',
    items_seen      INT NOT NULL DEFAULT 0,
    items_inserted  INT NOT NULL DEFAULT 0,
    items_updated   INT NOT NULL DEFAULT 0,
    items_unchanged INT NOT NULL DEFAULT 0,
    items_deleted   INT NOT NULL DEFAULT 0,
    error           TEXT,
    -- Per-source cursor for resumable runs (e.g. last sitemap entry processed).
    cursor          JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_runs_source_started ON ingestion_runs (source_id, started_at DESC);

-- =============================================================================
-- Documents & chunks  (architecture §4)
-- =============================================================================

CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    -- Stable identifier from the source. Sitemap URL, podcast GUID, or
    -- YouTube videoId. Used for change detection on subsequent runs.
    source_external_id TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    content_type    content_type NOT NULL,
    title           TEXT NOT NULL,
    publish_date    DATE,
    -- Body in plain text, normalised (whitespace collapsed). The HTML
    -- version is not stored: we re-fetch on change instead.
    body            TEXT NOT NULL,
    -- SHA-256 of the normalised body. Drives the second level of change
    -- detection (§3, two-level check).
    content_hash    TEXT NOT NULL,
    -- Source-side metadata captured at scrape time. Re-scraped on change.
    -- Examples: { "author":"Alice", "duration_seconds":2734, "video_id":"abc" }.
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Source-side tags ("scraped"). Distinct from admin_overrides so admin
    -- edits survive a re-scrape (§7).
    source_tags     TEXT[] NOT NULL DEFAULT '{}'::text[],
    -- Soft-delete: set when the item falls out of the source manifest.
    -- Nightly reconciliation hard-deletes after a grace period (§3).
    deleted_at      TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    indexed_at      TIMESTAMPTZ,           -- last AI Search upload time
    UNIQUE (source_id, source_external_id)
);
CREATE INDEX idx_documents_url       ON documents (source_url);
CREATE INDEX idx_documents_type_date ON documents (content_type, publish_date DESC);
CREATE INDEX idx_documents_alive     ON documents (deleted_at) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_tags      ON documents USING gin (source_tags);
CREATE INDEX idx_documents_meta      ON documents USING gin (source_metadata);

-- Admin tag overrides. Merged with source_tags at index-build time.
-- Architecture §7: 'admin edits never trigger a re-scrape but do trigger
-- a re-index'.
CREATE TABLE admin_overrides (
    document_id     UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    tags            TEXT[] NOT NULL DEFAULT '{}'::text[],
    updated_by      CITEXT NOT NULL,        -- email
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_overrides_tags ON admin_overrides USING gin (tags);

-- Audit log of admin metadata edits (§9 row-level audit).
CREATE TABLE admin_overrides_audit (
    id              BIGSERIAL PRIMARY KEY,
    document_id     UUID NOT NULL,
    tags_before     TEXT[],
    tags_after      TEXT[] NOT NULL,
    changed_by      CITEXT NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chunks (pre-embedding). Mirrors what's uploaded to AI Search but Postgres
-- is the durable source-of-truth: a re-index pulls from here, not from the
-- web. Embeddings themselves are stored in AI Search (vector field), not
-- here, to avoid double-storing 3072-float arrays.
CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INT  NOT NULL,
    -- Type-aware chunk text. For blog/case_study/product, includes the
    -- doc title and section heading prepended (§4). For video/podcast,
    -- carries a transcript window only.
    text            TEXT NOT NULL,
    -- For video/podcast chunks: the chunk's start offset, used to deep-link.
    timestamp_seconds INT,
    -- Section heading the chunk came from (blog/product), if any.
    section_heading TEXT,
    -- Token count from the embedding tokenizer (cl100k for OpenAI models).
    token_count     INT NOT NULL,
    -- Hash of (text + tags) — drives "did this chunk's index payload change?"
    -- decisions for partial re-indexing.
    payload_hash    TEXT NOT NULL,
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX idx_chunks_doc ON chunks (document_id);

-- =============================================================================
-- Auth & users
-- =============================================================================

-- We do not own the identity store — Entra ID is the IdP. This table
-- caches profile data observed in tokens, used for joining analytics rows
-- back to a human-readable name in the admin dashboard.
CREATE TABLE users (
    id              CITEXT PRIMARY KEY,     -- entra `oid` (object id)
    email           CITEXT NOT NULL UNIQUE,
    display_name    TEXT,
    -- Cached role. The token is still the source of truth at request time.
    role            app_role NOT NULL DEFAULT 'Standard.User',
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- Analytics  (architecture §7)
-- =============================================================================

CREATE TABLE queries (
    id              BIGSERIAL PRIMARY KEY,
    user_id         CITEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    query_text      TEXT NOT NULL,
    -- Result count after the no-results gate (i.e. 0 means user saw the
    -- no-results state, NOT a low-confidence list).
    result_count    INT NOT NULL,
    no_results      BOOLEAN NOT NULL,
    -- Top 5 result IDs as ordered, for offline relevance sampling.
    top_result_ids  UUID[] NOT NULL DEFAULT '{}',
    -- Latency in ms, end-to-end inside the API process.
    latency_ms      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_queries_created      ON queries (created_at DESC);
CREATE INDEX idx_queries_user_created ON queries (user_id, created_at DESC);
CREATE INDEX idx_queries_zero         ON queries (created_at DESC) WHERE no_results;
CREATE INDEX idx_queries_text_trgm    ON queries USING gin (query_text gin_trgm_ops);
                                     -- (requires pg_trgm; optional)

CREATE TABLE clicks (
    id              BIGSERIAL PRIMARY KEY,
    query_id        BIGINT REFERENCES queries(id) ON DELETE SET NULL,
    user_id         CITEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    document_id     UUID REFERENCES documents(id) ON DELETE SET NULL,
    content_type    content_type,
    position        INT NOT NULL,
    clicked_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_clicks_query  ON clicks (query_id);
CREATE INDEX idx_clicks_doc    ON clicks (document_id);
CREATE INDEX idx_clicks_recent ON clicks (clicked_at DESC);

-- =============================================================================
-- Issue queue  (architecture §7)
-- =============================================================================

CREATE TABLE issues (
    id              BIGSERIAL PRIMARY KEY,
    user_id         CITEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    kind            issue_kind NOT NULL,
    status          issue_status NOT NULL DEFAULT 'open',
    -- The query the user was running when they reported, if any.
    query_text      TEXT,
    -- The result they were complaining about, if any.
    document_id     UUID REFERENCES documents(id) ON DELETE SET NULL,
    message         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);
CREATE INDEX idx_issues_open ON issues (created_at DESC) WHERE status = 'open';
CREATE INDEX idx_issues_user ON issues (user_id);

-- =============================================================================
-- Helpful views for the admin dashboard
-- =============================================================================

CREATE VIEW v_zero_result_top AS
SELECT
    query_text,
    COUNT(*)            AS occurrences,
    MAX(created_at)     AS last_seen,
    COUNT(DISTINCT user_id) AS distinct_users
FROM queries
WHERE no_results
GROUP BY query_text
ORDER BY occurrences DESC, last_seen DESC;

CREATE VIEW v_top_queries_7d AS
SELECT
    query_text,
    COUNT(*) AS n,
    AVG(result_count)::numeric(10,2) AS avg_results,
    AVG(latency_ms)::numeric(10,2)   AS avg_latency_ms
FROM queries
WHERE created_at >= now() - INTERVAL '7 days'
GROUP BY query_text
ORDER BY n DESC
LIMIT 100;

CREATE VIEW v_clicked_content_types_7d AS
SELECT content_type, COUNT(*) AS n
FROM clicks
WHERE clicked_at >= now() - INTERVAL '7 days'
  AND content_type IS NOT NULL
GROUP BY content_type
ORDER BY n DESC;

-- =============================================================================
-- Notes
-- =============================================================================
-- 1. Row-level security (production §9): enable per-table policies that
--    restrict admin_overrides_audit reads to admin role and queries reads
--    to the owning user_id. Omitted here for clarity.
-- 2. The retrieval index itself (BM25 + vectors + semantic ranker) lives
--    in Azure AI Search. The mapping from this schema to the AI Search
--    index payload is in ../dataset/ai-search-payload.jsonl, and the
--    index definition is in ai-search-index.json.
