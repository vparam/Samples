# AI-Driven Content Discovery for MJS Packaging

**Architecture Write-up**

## 1. Problem framing

MJS Packaging publishes a steady stream of content (blog posts, case studies, product pages, podcast episodes, and YouTube videos), but internal teams cannot easily find it during real workflows. As Tom emphasised, "they just need better discovery over the content corpus they have." This is fundamentally a discovery problem, not a knowledge or reasoning problem. The system is a retrieval engine, not an answer engine. Three constraints flow from that framing and shape every decision in this document.

**Retrieval quality is the product.** Ranking the right asset into the top three results for queries like "do we have any case studies about pharma-grade glass containers?" is the core success metric. AI is applied narrowly and deliberately: to improve semantic retrieval and ranking (embeddings, query understanding, re-ranking), not to generate answers.

**Grounding is enforced by the architecture, not by prompting.** The MVP has no LLM in the response path. The Search API can only return items that already exist in the index. Hallucination is not "prevented"; it is structurally impossible.

**Microsoft alignment is a feature, not a constraint.** MJS is a Microsoft / Entra ID shop. Choosing Azure-native services where they are best-of-class (AI Search, Entra ID, Application Insights) reduces operational burden and shortens the path to a Copilot or Teams integration in a later phase.

The system serves two roles, Standard (search and view) and Admin (search, edit metadata, review the issue queue and analytics), over an internal-only, mobile-first interface gated by Entra ID SSO.

## 2. Architecture overview

```
Sources  →  Ingestion  →  Processing  →  Index (AI Search)  →  Search API  →  Web UI
```

Push-based notifications and a 5-minute poller share a single set of per-source workers; processed content is written to a hybrid retrieval index; and the read path is a stateless Search API consumed by a mobile-first Web UI and an Admin UI. Entra ID, Application Insights, and Azure OpenAI are cross-cutting services. The remaining sections justify each component.

*Figure 1. End-to-end architecture. Push notifications and a 5-minute poller share per-source workers; processed content is written to a hybrid retrieval index; the read path is a stateless Search API.*

### Why this architecture (alternatives considered)

Before settling on hybrid retrieval, four other system shapes were considered and rejected:

- **Pure keyword (BM25) search.** Misses semantic intent on queries like "why work with us," where matching content uses different vocabulary than the query.
- **Pure vector search.** Weak on exact entity and product-name match, which is half the expected query distribution at MJS (specific case studies, materials, customer segments).
- **LLM answer generation as the default response path.** Breaks the grounding constraint by construction and is not what the brief asked for. The corpus is the answer; surfacing the right link beats summarising it.
- **Knowledge graph or structured ontology.** Requires manual schema curation that does not scale to a corpus refreshed every 5 minutes from three different source types.

Hybrid retrieval with semantic re-rank is the smallest design that handles both query shapes (vague intent and entity-anchored) while preserving grounding.

## 3. Ingestion and change detection

**Per-source workers, not a generic crawler.** Each source has materially different access patterns: the website is HTML behind a sitemap, YouTube exposes a typed API with caption tracks, and the podcast is an RSS feed with enclosed media. Building a generic crawler would either lose source-specific signal (publish date precision, video chapters, episode duration) or accumulate special cases until it is a per-source crawler in disguise. Three small workers sharing common processing downstream is the cleaner pattern.

**Hybrid push and poll, with push preferred where available.** Polling at 5-minute cadence on every source is wasteful and is not, in fact, 5 minutes from publish. Push where the source supports it, polling as a fallback:

- **YouTube:** subscribe to the channel feed via WebSub (PubSubHubbub). New uploads notify our endpoint within seconds.
- **Podcast RSS:** if the feed advertises a hub, subscribe via WebSub; if not, poll every 5 minutes.
- **Website:** poll the sitemap every 5 minutes, using the sitemap's `lastmod` field plus HTTP `If-Modified-Since` and `ETag` headers to skip unchanged pages cheaply.

**Change detection is a two-level check.** An HTTP-level check (ETag / Last-Modified) avoids re-downloading. For pages that do return content, a SHA-256 hash of the normalised text decides whether to re-process. Without normalisation, trivial markup churn (analytics scripts, rotating banner content) would invalidate hashes and cause needless re-embedding, which is the most expensive step in the pipeline.

**Deletion handling.** Items are marked stale when they fall out of the source manifest (sitemap entry removed, video taken down, episode unpublished). A nightly reconciliation pass removes stale items from the index. Soft-delete first, so accidental source-side mistakes are recoverable. Workers are Azure Container Apps Jobs triggered by either WebSub callbacks or a 5-minute Cron schedule, with checkpoint state in Postgres so a crash mid-run does not duplicate or skip items.

## 4. Indexing: chunking, embeddings, search engine

**Type-aware chunking.** Chunking is one of the highest-leverage decisions in any retrieval system. Different content types need different strategies, and applying a single rule across all of them visibly degrades quality.

- **Blog posts and case studies:** token-based chunks (~700 tokens, 80-token overlap), with the document title and section heading prepended to each chunk. Heading context lifts retrieval on queries that use heading vocabulary the body doesn't repeat.
- **Product and spec pages:** split on H2/H3 sections; tables stay intact within a chunk. Splitting a spec table mid-row destroys the row-to-value relationship the user is searching for.
- **Podcast and YouTube transcripts:** fixed time-window chunks (~75 seconds, ~600 tokens), each carrying the start timestamp. Queries can resolve to a deep-link such as `youtu.be/…?t=312` so the user lands on the relevant moment, not just the video.

**Embedding model: Azure OpenAI `text-embedding-3-large` (3072 dims).** Chosen because it is the strongest general-purpose embedding model available within Azure today, outperforming `text-embedding-3-small` and `ada-002` on standard retrieval benchmarks (MTEB), and available with the same Azure subscription and managed identity that the rest of the stack uses. Routing through Azure OpenAI rather than the public OpenAI endpoint keeps embeddings inside MJS's Azure tenant boundary and inherits its DLP and audit controls. A self-hosted open-source model such as `bge-large-en` was rejected for the prototype: it would shave per-token cost but adds GPU hosting, a model serving stack, and version-management overhead, which is a poor trade for a corpus measured in hundreds of documents.

**Search engine: Azure AI Search.** Native hybrid retrieval (BM25 + vector), a built-in semantic re-ranker (an L2 cross-encoder trained on Bing relevance judgments), Entra ID-integrated access control, and per-document metadata filtering. Alternatives:

- **Pinecone or Weaviate:** competent vector stores, but neither offers the semantic re-ranker, both add a vendor outside the Microsoft tenant, and both still require a separate keyword index for the BM25 half.
- **Postgres pgvector:** attractive for prototype simplicity but loses the semantic re-ranker; on a Microsoft-aligned production deployment it would mean rebuilding capabilities AI Search already provides.
- **Elasticsearch:** strong on the keyword side but less mature on hybrid retrieval; operationally heavier than AI Search for an internal tool of this scale.

The semantic re-ranker is the deciding feature. On the example queries in the brief, including "why should a customer work with us?" and similar vague-intent queries, the re-ranker noticeably improves top-3 ordering over plain hybrid retrieval. It is invoked only on the top ~50 hybrid candidates, so latency stays within budget.

## 5. Retrieval and ranking

A query flows through three stages.

- **Hybrid retrieval.** Azure AI Search returns the top 50 candidates using reciprocal rank fusion of BM25 and vector cosine similarity. RRF is robust to score-scale differences between the two halves and does not require manual weight tuning.
- **Semantic re-rank.** The top 50 are re-ranked by the AI Search semantic ranker, which scores candidates using a transformer cross-encoder. This is the step that converts coarse "topically related" results into "right answer at position 1."
- **Recency boost.** A bounded recency multiplier (an exponential decay over publish age, capped at 1.3×) is applied to the semantic score. Bounded so a stale-but-perfect match still beats a recent-but-irrelevant one. Recency tilts close calls; it doesn't override relevance.

**No-results behaviour.** The semantic ranker returns a confidence score per result. If the top result's score falls below a tuned threshold, the API returns an empty list with a `no_results` flag rather than padding with weak matches. The threshold is tuned against the golden eval set (Section 8). This is deliberately stricter than necessary: a confident "no results" is better for trust than a low-confidence speculative match.

**The result card.** Each result returns title, content type, publish date, source URL, and a contextual excerpt (the matched chunk, with the matching span highlighted). For video and podcast results, the URL is timestamp-deep-linked.

## 6. Grounding architecture

The brief's hardest requirement is that grounding be enforced architecturally, not by prompting. Three layers do this work.

**Layer 1: No generation path in the MVP.** The Search API's response shape is a list of result cards. There is no LLM in the request flow. It is physically impossible for the API to return text that does not exist in the index, because no component capable of producing such text is present. This is the strongest possible form of grounding and the right default for an MVP whose purpose is link discovery.

**Layer 2: Forward-compatibility for a future synthesis layer.** When summarisation is added (see Section 10), grounding is preserved by construction: the LLM only ever receives retrieved chunks as input context; the system prompt forbids drawing on world knowledge; every generated sentence must carry a citation token that resolves to a retrieved chunk; and a post-generation validator strips any sentence whose citation does not resolve. The validator is the load-bearing piece; prompts can drift, validators can be regression-tested.

**Layer 3: Adversarial evaluation in CI.** The golden set (Section 8) includes adversarial queries with no expected results, such as "What's the population of Tokyo?", "Who is the current US president?", that should always return the no-results state. CI fails if any of these returns content. This prevents accidental loosening of the grounding constraint over time.

## 7. Identity, analytics, and admin tooling

**Authentication: Entra ID with app roles.** OIDC code flow with PKCE. Two app roles (`Standard.User` and `Admin`) issued via Entra group membership and included in the access token, then enforced at the API layer. Tokens are short-lived (1 hour); refresh on focus. Re-authentication is required after the IT-policy session window. The prototype mocks SSO with the same token shape (`sub`, `email`, `roles` claim) so the swap to real Entra ID is mechanical: change the JWKS endpoint and the audience.

**Analytics.** Every query is recorded to Postgres with user object ID (for audit), query text, result count, top result IDs, timestamps, and click-through events emitted from the UI. Zero-result queries land in a separate table that drives the admin dashboard. Application Insights captures infrastructure metrics: latency, error rate, and ingestion lag.

**Admin tooling.** The Admin UI surfaces (a) tag editing on indexed content, written to an `admin_overrides` table that is merged with scraped metadata at index time, so admin edits never trigger a re-scrape but do trigger a re-index, (b) the issue-report queue with status tracking, and (c) the analytics dashboard: top queries, zero-result queries by frequency, content types most surfaced and clicked, and query volume over time.

## 8. Evaluation: how we know it's working

A 40-query golden set covers four categories: vague intent ("why work with us"), entity-anchored ("pharma-grade glass case study"), temporal ("recent supply chain content"), and adversarial / out-of-corpus. Relevance is labelled 0/1/2 across the top 10 of each query, drawn from a current full-index search.

Metrics tracked: Recall@5, MRR, nDCG@10, and zero-result precision (the percentage of out-of-corpus queries that correctly return no results). The eval runs in CI on every change to chunking, embedding, or ranking code; the PR comment shows per-metric deltas vs. main. A regression on any metric is a blocking review comment, not an automatic block; sometimes the trade is justified. Online metrics complement the offline set: click-through rate by result position, query reformulation rate, and time-to-click.

## 9. What changes for a 12-week production engagement

Ordered roughly by risk reduction. Things that do not change: the retrieval-first framing, the no-LLM-in-response-path grounding constraint, and the architectural shape in Section 2.

- **Ingestion:** polling-only ➜ WebSub push subscriptions for YouTube and the podcast feed, with polling as fallback.
- **Auth:** mocked SSO ➜ real Entra ID with app roles, group sync, and conditional-access policies.
- **Eval:** ad-hoc golden set ➜ versioned in source control, run in CI, surfaced in PR comments, with a weekly online-metrics review.
- **Cost and observability:** unmonitored ➜ embedding-spend dashboard, query latency p50/p95 dashboards, alerting on ingestion lag > 10 minutes and zero-result-rate spikes.
- **Resilience:** single-region ➜ paired-region AI Search with index replica, circuit breakers on outbound source APIs (YouTube quota), retry-with-backoff on Azure OpenAI throttling.
- **Security:** dev secrets ➜ Key Vault with managed identity for every service, network isolation via private endpoints, row-level audit on admin metadata edits.

## 10. Microsoft 365 / Copilot integration as a future phase

Two viable paths, with different trade-offs.

**Option A: Microsoft 365 Copilot connector via Graph Connectors.** Index our content into the M365 search graph; users query through Copilot natively in Word, Outlook, and Teams. Deepest integration; users do not learn a new tool. Trade-off: ranking is Microsoft's, so we lose direct control over the recency boost and the no-results threshold. Suitable once the M365 graph's relevance has been validated against MJS queries.

**Option B: a Teams app or bot wrapping our existing API.** A search bar inside Teams that hits our Search API. Keeps full control of retrieval, ranking, and grounding. Lighter integration: users still go to a search-MJS-content surface, just without leaving Teams. Recommended sequence is B then A: B ships in weeks and validates the retrieval-quality bar in a real workflow context; A ships once that bar is documented and we are confident in defending the move to Microsoft-controlled ranking.
