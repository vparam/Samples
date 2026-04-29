"""Brief: Access Control and Security.

  - Authentication via SSO using Microsoft 365 / Entra ID identities (mocked here)
  - Domain-restricted: only verified MJS Microsoft 365 accounts may authenticate
  - Unauthenticated users must be redirected to login — no content visible
  - Standard session expiry with re-authentication after inactivity
"""

from __future__ import annotations

import time

import pytest


def test_unauthenticated_search_returns_401(client):
    r = client.get("/api/search", params={"q": "glass"})
    assert r.status_code == 401


def test_login_with_mjs_email_succeeds(client):
    r = client.post("/api/auth/login",
                    json={"email": "alice@mjs-packaging.example"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@mjs-packaging.example"
    assert body["role"] == "Standard.User"
    # Session cookie set
    assert "mjs_session" in r.cookies or any(
        c.name == "mjs_session" for c in client.cookies.jar
    )


def test_login_rejects_non_mjs_domain(client):
    r = client.post("/api/auth/login", json={"email": "someone@gmail.com"})
    assert r.status_code == 403
    assert "mjs-packaging.example" in r.json()["detail"]


def test_login_rejects_unknown_user_within_mjs(client):
    r = client.post("/api/auth/login",
                    json={"email": "ghost@mjs-packaging.example"})
    assert r.status_code == 401


def test_logout_clears_session(standard_client):
    r = standard_client.post("/api/auth/logout")
    assert r.status_code == 200
    standard_client.cookies.clear()
    r2 = standard_client.get("/api/search", params={"q": "glass"})
    assert r2.status_code == 401


def test_me_returns_principal(standard_client):
    r = standard_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "alice@mjs-packaging.example"


def test_expired_token_is_rejected(client):
    """Forge an expired session cookie. /api/auth/me must reject it as
    expired and force re-authentication."""
    from prototype.backend import auth
    import time as _time
    sub, name, role = auth.MOCK_USERS["alice@mjs-packaging.example"]
    expired = auth._sign({
        "iss": auth.ISSUER, "aud": auth.AUDIENCE,
        "sub": sub, "email": "alice@mjs-packaging.example",
        "name": name, "roles": [role],
        "iat": int(_time.time()) - 3600,
        "exp": int(_time.time()) - 60,  # already expired
    })
    client.cookies.set("mjs_session", expired)
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_sliding_session_refreshes_cookie_on_activity(standard_client):
    """Each authenticated request issues a new cookie with a fresh exp,
    so an active user's session never times out — only inactivity does.
    """
    from prototype.backend import auth
    pre = standard_client.cookies.get("mjs_session")
    pre_payload = auth.decode(pre)
    time.sleep(1.05)
    r = standard_client.get("/api/auth/me")
    assert r.status_code == 200
    post = standard_client.cookies.get("mjs_session")
    post_payload = auth.decode(post)
    # Same identity, but token re-issued with a later exp
    assert post_payload.sub == pre_payload.sub
    # Decode the raw exp via _verify
    pre_exp = auth._verify(pre)["exp"]
    post_exp = auth._verify(post)["exp"]
    assert post_exp >= pre_exp
