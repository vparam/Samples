"""Mock SSO with the Entra ID token shape.

Architecture writeup section 7: 'The prototype mocks SSO with the same
token shape (sub, email, roles claim) so the swap to real Entra ID is
mechanical: change the JWKS endpoint and the audience.'

The mock signs tokens with a fixed HS256-equivalent (HMAC-SHA256) key.
We hand-roll a JWT-shaped token to avoid the PyJWT/cryptography chain,
which is broken on some Linux dists. Production would validate RS256
tokens against Entra's JWKS via msal/python-jose with cryptography
properly installed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Cookie, HTTPException, status

SECRET = os.environ.get("MJS_DEV_SECRET", "dev-only-not-for-production")
ISSUER = "https://mock-entra.local/mjs"
AUDIENCE = "mjs-discovery-prototype"
ALLOWED_DOMAIN = "mjs-packaging.example"
TOKEN_TTL_SECONDS = 60 * 60  # 1 hour, matches architecture section 7


@dataclass
class Principal:
    sub: str
    email: str
    name: str
    role: str  # "Standard.User" or "Admin"

    @property
    def is_admin(self) -> bool:
        return self.role == "Admin"


# Mock user directory. In production, identities come from Entra ID tokens.
MOCK_USERS = {
    "alice@mjs-packaging.example": ("user-alice", "Alice Standard", "Standard.User"),
    "tom@mjs-packaging.example":   ("user-tom",   "Tom Admin",      "Admin"),
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: dict) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"},
                                separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(SECRET.encode(), f"{header}.{body}".encode(),
                   hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"


def _verify(token: str) -> dict:
    try:
        header_b64, body_b64, sig_b64 = token.split(".")
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session.")
    expected = hmac.new(
        SECRET.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session.")
    try:
        payload = json.loads(_b64url_decode(body_b64))
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session.")
    if payload.get("iss") != ISSUER or payload.get("aud") != AUDIENCE:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session.")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Session expired. Please sign in again.",
        )
    return payload


def issue_token(email: str) -> str:
    email_lc = email.lower().strip()
    if not email_lc.endswith("@" + ALLOWED_DOMAIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only @{ALLOWED_DOMAIN} accounts may sign in.",
        )
    if email_lc not in MOCK_USERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user. Use alice@mjs-packaging.example or tom@mjs-packaging.example.",
        )
    sub, name, role = MOCK_USERS[email_lc]
    now = int(time.time())
    payload = {
        "iss": ISSUER, "aud": AUDIENCE,
        "sub": sub, "email": email_lc, "name": name,
        "roles": [role],
        "iat": now, "exp": now + TOKEN_TTL_SECONDS,
    }
    return _sign(payload)


def decode(token: str) -> Principal:
    payload = _verify(token)
    roles = payload.get("roles") or []
    role = "Admin" if "Admin" in roles else "Standard.User"
    return Principal(
        sub=payload["sub"], email=payload["email"],
        name=payload.get("name", payload["email"]), role=role,
    )


def require_user(mjs_session: str | None = Cookie(default=None)) -> Principal:
    if not mjs_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required.")
    return decode(mjs_session)


def require_admin(mjs_session: str | None = Cookie(default=None)) -> Principal:
    p = require_user(mjs_session)
    if not p.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required.")
    return p
