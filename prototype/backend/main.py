"""FastAPI app: search, ingest, admin tags, issue queue, analytics, mock SSO.

Read path: query → /api/search → SQLite-backed hybrid retrieval → JSON
result cards. There is no LLM in this path. The Search API can only
return content present in the index. (Architecture section 6, layer 1.)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import (
    Body, Depends, FastAPI, HTTPException, Query, Request, Response, status,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, db, ingestion, scheduler
from .search import get_index

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="MJS Discovery Prototype", version="0.1")


# -- startup ---------------------------------------------------------------

@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    # Auto-seed on first run so the demo works out of the box.
    with db.connect() as cx:
        n = cx.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE deleted_at IS NULL"
        ).fetchone()["n"]
    if n == 0:
        ingestion.ingest_seed()
    get_index().load()
    # Optional periodic ingestion driver (architecture §3, 5-min poll).
    # Off unless MJS_SCHEDULER=on so tests and `uvicorn --reload` don't
    # double-fire ingestion. Admins can also tick manually via
    # POST /api/admin/scheduler/tick.
    scheduler.start_background()


@app.on_event("shutdown")
def _shutdown() -> None:
    scheduler.stop_background()


# -- sliding session middleware -------------------------------------------

@app.middleware("http")
async def sliding_session(request: Request, call_next):
    """Re-issue the session cookie on every authenticated request so the
    inactivity timer resets (brief: 're-authentication after inactivity').
    Skipped for /api/auth/* so login/logout retain control of the cookie.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/auth/"):
        return response
    token = request.cookies.get("mjs_session")
    if not token:
        return response
    try:
        principal = auth.decode(token)
    except HTTPException:
        return response
    new_token = auth.refresh_token(principal)
    response.set_cookie(
        key="mjs_session", value=new_token, httponly=True, samesite="lax",
        max_age=auth.TOKEN_TTL_SECONDS, path="/",
    )
    return response


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- auth ------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response) -> dict:
    token = auth.issue_token(body.email)
    response.set_cookie(
        key="mjs_session", value=token, httponly=True, samesite="lax",
        max_age=auth.TOKEN_TTL_SECONDS, path="/",
    )
    p = auth.decode(token)
    return {"email": p.email, "name": p.name, "role": p.role}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("mjs_session", path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(p: auth.Principal = Depends(auth.require_user)) -> dict:
    return {"email": p.email, "name": p.name, "role": p.role}


# -- search ----------------------------------------------------------------

@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1, max_length=500),
    p: auth.Principal = Depends(auth.require_user),
) -> dict:
    out = get_index().search(q, k=10)

    with db.connect() as cx:
        cur = cx.execute(
            """INSERT INTO queries
                 (user_id, user_email, query_text, result_count,
                  no_results, top_result_ids, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (p.sub, p.email, q, len(out["results"]),
             1 if out["no_results"] else 0,
             json.dumps([r["document_id"] for r in out["results"][:5]]),
             _now()),
        )
        query_id = cur.lastrowid
    out["query_id"] = query_id
    return out


class ClickEvent(BaseModel):
    query_id: int
    document_id: int
    position: int
    content_type: str | None = None


@app.post("/api/search/click")
def search_click(
    ev: ClickEvent, p: auth.Principal = Depends(auth.require_user)
) -> dict:
    with db.connect() as cx:
        cx.execute(
            """INSERT INTO clicks
                 (query_id, document_id, content_type, position, user_id, clicked_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ev.query_id, ev.document_id, ev.content_type, ev.position, p.sub, _now()),
        )
    return {"ok": True}


# -- ingestion -------------------------------------------------------------

@app.post("/api/ingest/seed")
def ingest_seed(p: auth.Principal = Depends(auth.require_admin)) -> dict:
    counts = ingestion.ingest_seed()
    get_index().load()
    return counts


class FeedIngestRequest(BaseModel):
    feed_url: str
    content_type: str = "blog"


@app.post("/api/ingest/rss")
def ingest_rss_endpoint(
    body: FeedIngestRequest, p: auth.Principal = Depends(auth.require_admin),
) -> dict:
    counts = ingestion.ingest_rss(body.feed_url, body.content_type)
    get_index().load()
    return counts


@app.post("/api/ingest/sitemap")
def ingest_sitemap_endpoint(
    body: FeedIngestRequest, p: auth.Principal = Depends(auth.require_admin),
) -> dict:
    """Sitemap-driven website crawl (brief: 'use the public sitemap as the
    discovery starting point so nothing is missed')."""
    counts = ingestion.ingest_sitemap(
        body.feed_url, default_content_type=body.content_type,
    )
    get_index().load()
    return counts


@app.get("/api/sources")
def sources(p: auth.Principal = Depends(auth.require_user)) -> dict:
    return {"sources": ingestion.list_sources()}


# -- managed sources & scheduler ------------------------------------------

class SourceUpsertRequest(BaseModel):
    kind: str = Field(pattern=r"^(sitemap|rss|youtube_websub)$")
    feed_url: str
    default_content_type: str = "blog"
    enabled: bool = True
    poll_interval_seconds: int = 300


@app.get("/api/admin/sources")
def list_managed_sources(p: auth.Principal = Depends(auth.require_admin)) -> dict:
    return {"sources": ingestion.list_sources_table()}


@app.post("/api/admin/sources")
def upsert_managed_source(
    body: SourceUpsertRequest, p: auth.Principal = Depends(auth.require_admin),
) -> dict:
    sid = ingestion.upsert_source(
        kind=body.kind, feed_url=body.feed_url,
        default_content_type=body.default_content_type,
        enabled=body.enabled, poll_interval_seconds=body.poll_interval_seconds,
    )
    return {"ok": True, "id": sid}


@app.post("/api/admin/scheduler/tick")
def scheduler_tick(p: auth.Principal = Depends(auth.require_admin)) -> dict:
    """Run the scheduler one cycle synchronously. Useful for demos and
    for the test suite. The background scheduler is normally off in
    development."""
    results = scheduler.run_one_cycle()
    get_index().load()
    return {"ran": results}


# -- YouTube WebSub callback (architecture §3, push-pipeline) -------------
# The hub does GET for subscription verification (echoing hub.challenge)
# and POST for content delivery. The POST body is signed; we verify
# X-Hub-Signature against the subscription secret before ingesting.

import hashlib
import hmac as _hmac


@app.get("/webhooks/youtube/websub")
def websub_verify(
    request: Request,
    challenge: str = Query(..., alias="hub.challenge"),
    mode: str = Query(..., alias="hub.mode"),
    topic: str = Query(..., alias="hub.topic"),
):
    """Subscription verification handshake. Echo hub.challenge as plain
    text on success; otherwise 404 (hub will retry / give up)."""
    if mode not in ("subscribe", "unsubscribe"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad hub.mode")
    with db.connect() as cx:
        row = cx.execute(
            "SELECT 1 FROM websub_subscriptions WHERE topic_url = ?", (topic,),
        ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown topic")
    return Response(content=challenge, media_type="text/plain")


@app.post("/webhooks/youtube/websub")
async def websub_callback(request: Request) -> dict:
    """Signed push delivery from the WebSub hub. Verify HMAC-SHA1 signature
    against the per-subscription secret, then ingest the Atom payload."""
    body = await request.body()
    sig_header = request.headers.get("X-Hub-Signature", "")
    if not sig_header.startswith("sha1="):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing signature")
    provided = sig_header.split("=", 1)[1].strip()

    # We don't know which subscription this is for without the topic; the
    # WebSub spec carries it inside the Atom payload. Cheap: try all known
    # secrets — acceptable for one channel; for many, look up by
    # topic-from-payload first.
    with db.connect() as cx:
        rows = cx.execute("SELECT secret FROM websub_subscriptions").fetchall()
    matched = False
    for r in rows:
        expected = _hmac.new(r["secret"].encode(), body, hashlib.sha1).hexdigest()
        if _hmac.compare_digest(expected, provided):
            matched = True
            break
    if not matched:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad signature")

    counts = ingestion.ingest_youtube_payload(body)
    get_index().load()
    return {"ok": True, "counts": counts}


class WebsubSubscribeRequest(BaseModel):
    topic_url: str
    secret: str = Field(min_length=8, max_length=200)


@app.post("/api/admin/websub/subscribe")
def admin_subscribe(
    body: WebsubSubscribeRequest, p: auth.Principal = Depends(auth.require_admin),
) -> dict:
    """Register a WebSub subscription record locally. (In production
    this would also POST to the hub's /subscribe endpoint; for the
    prototype the row is enough to verify and accept callbacks.)"""
    with db.connect() as cx:
        cx.execute(
            """INSERT INTO websub_subscriptions (topic_url, secret, verified_at)
               VALUES (?, ?, ?)
               ON CONFLICT(topic_url) DO UPDATE SET secret = excluded.secret""",
            (body.topic_url, body.secret, _now()),
        )
    return {"ok": True}


# -- admin: tag editing ----------------------------------------------------

class TagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list)


@app.put("/api/admin/documents/{doc_id}/tags")
def update_tags(
    doc_id: int, body: TagsUpdate,
    p: auth.Principal = Depends(auth.require_admin),
) -> dict:
    """Admin metadata edit. Per architecture section 7, this writes to
    admin_overrides and triggers a re-index, NOT a re-scrape."""
    with db.connect() as cx:
        if not cx.execute(
            "SELECT 1 FROM documents WHERE id = ? AND deleted_at IS NULL",
            (doc_id,),
        ).fetchone():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
        cx.execute(
            """INSERT INTO admin_overrides (document_id, tags, updated_by, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(document_id) DO UPDATE SET
                 tags = excluded.tags,
                 updated_by = excluded.updated_by,
                 updated_at = excluded.updated_at""",
            (doc_id, json.dumps(body.tags), p.email, _now()),
        )
    get_index().load()
    return {"ok": True, "tags": body.tags}


@app.get("/api/admin/documents")
def list_documents(p: auth.Principal = Depends(auth.require_admin)) -> dict:
    with db.connect() as cx:
        rows = cx.execute(
            """SELECT d.id, d.source_url, d.content_type, d.title, d.publish_date,
                      d.fetched_at, COALESCE(s.tags,'[]') AS source_tags,
                      COALESCE(a.tags,'[]') AS admin_tags
               FROM documents d
               LEFT JOIN source_tags s ON s.document_id = d.id
               LEFT JOIN admin_overrides a ON a.document_id = d.id
               WHERE d.deleted_at IS NULL
               ORDER BY d.publish_date DESC NULLS LAST"""
        ).fetchall()
    docs = []
    for r in rows:
        docs.append({
            "id": r["id"], "source_url": r["source_url"],
            "content_type": r["content_type"], "title": r["title"],
            "publish_date": r["publish_date"], "fetched_at": r["fetched_at"],
            "source_tags": json.loads(r["source_tags"]),
            "admin_tags": json.loads(r["admin_tags"]),
        })
    return {"documents": docs}


# -- issue reporting -------------------------------------------------------

class IssueReport(BaseModel):
    kind: str = Field(pattern=r"^(broken_link|wrong_result|missing_content|other)$")
    query_text: str | None = None
    document_id: int | None = None
    message: str | None = Field(default=None, max_length=2000)


@app.post("/api/issues")
def submit_issue(
    body: IssueReport, p: auth.Principal = Depends(auth.require_user)
) -> dict:
    with db.connect() as cx:
        cur = cx.execute(
            """INSERT INTO issues
                 (user_id, user_email, kind, query_text, document_id, message,
                  status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
            (p.sub, p.email, body.kind, body.query_text, body.document_id,
             body.message, _now()),
        )
    return {"ok": True, "issue_id": cur.lastrowid}


class IssueUpdate(BaseModel):
    status: str = Field(pattern=r"^(open|in_progress|resolved|wont_fix)$")


@app.get("/api/admin/issues")
def list_issues(p: auth.Principal = Depends(auth.require_admin)) -> dict:
    with db.connect() as cx:
        rows = cx.execute(
            """SELECT i.*, d.title AS doc_title, d.source_url AS doc_url
               FROM issues i LEFT JOIN documents d ON d.id = i.document_id
               ORDER BY (i.status = 'open') DESC, i.created_at DESC"""
        ).fetchall()
    return {"issues": [dict(r) for r in rows]}


@app.put("/api/admin/issues/{issue_id}")
def update_issue(
    issue_id: int, body: IssueUpdate,
    p: auth.Principal = Depends(auth.require_admin),
) -> dict:
    with db.connect() as cx:
        if not cx.execute("SELECT 1 FROM issues WHERE id=?", (issue_id,)).fetchone():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found")
        cx.execute("UPDATE issues SET status=? WHERE id=?", (body.status, issue_id))
    return {"ok": True}


# -- analytics -------------------------------------------------------------

@app.get("/api/admin/analytics")
def analytics(p: auth.Principal = Depends(auth.require_admin)) -> dict:
    with db.connect() as cx:
        top_queries = cx.execute(
            """SELECT query_text, COUNT(*) AS n
               FROM queries GROUP BY query_text
               ORDER BY n DESC, MAX(created_at) DESC LIMIT 10"""
        ).fetchall()
        zero_results = cx.execute(
            """SELECT query_text, COUNT(*) AS n
               FROM queries WHERE no_results = 1
               GROUP BY query_text
               ORDER BY n DESC, MAX(created_at) DESC LIMIT 10"""
        ).fetchall()
        clicked_types = cx.execute(
            """SELECT content_type, COUNT(*) AS n
               FROM clicks WHERE content_type IS NOT NULL
               GROUP BY content_type ORDER BY n DESC"""
        ).fetchall()
        volume = cx.execute(
            """SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n
               FROM queries GROUP BY day ORDER BY day DESC LIMIT 14"""
        ).fetchall()
        totals = cx.execute(
            """SELECT
                 (SELECT COUNT(*) FROM queries) AS total_queries,
                 (SELECT COUNT(*) FROM queries WHERE no_results=1) AS zero_result_queries,
                 (SELECT COUNT(*) FROM clicks) AS total_clicks,
                 (SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL) AS indexed_documents"""
        ).fetchone()
    return {
        "totals": dict(totals),
        "top_queries": [dict(r) for r in top_queries],
        "zero_result_queries": [dict(r) for r in zero_results],
        "clicked_content_types": [dict(r) for r in clicked_types],
        "daily_volume": [dict(r) for r in volume],
    }


# -- prompting guide -------------------------------------------------------

@app.get("/api/guide")
def guide() -> dict:
    return {
        "title": "How to search MJS content",
        "sections": [
            {
                "heading": "What this tool does",
                "body": (
                    "Searches MJS-published content (blog posts, case studies, "
                    "product pages, podcasts, videos) and returns ranked links "
                    "to the original sources. It does not generate answers — "
                    "every result is a real published item."
                ),
            },
            {
                "heading": "What this tool does NOT do",
                "body": (
                    "It will not answer general-knowledge questions, summarise "
                    "for you, or invent content. If nothing in the indexed "
                    "corpus matches your query, you will see a clear no-results "
                    "state rather than a fabricated answer."
                ),
            },
            {
                "heading": "Effective queries",
                "body": (
                    "Natural-language is fine: 'do we have any case studies "
                    "on pharma-grade glass?' works as well as keywords. Mention "
                    "the content type if you only want one ('podcast about "
                    "cold chain'). For recent content, just say 'recent'."
                ),
            },
            {
                "heading": "If you cannot find what you expect",
                "body": (
                    "Use the report-issue link on the results page. Tell us "
                    "the query and what you expected to see. Admins review "
                    "the queue weekly."
                ),
            },
        ],
    }


# -- static frontend -------------------------------------------------------

@app.get("/")
def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
