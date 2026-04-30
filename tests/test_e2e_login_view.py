"""End-to-end login-view check.

Drives the legacy frontend (prototype/frontend/index.html) in real headless
Chromium via Puppeteer and asserts the auth flow makes the login section
actually disappear after sign-in (computed CSS, not just the [hidden]
attribute) and reappear after sign-out, for both Standard and Admin roles.

Skipped automatically when the Node deps are not installed:

    npm install --prefix tests/e2e

The harness manages its own uvicorn process and SQLite DB, so it does not
collide with a dev server you may have running.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = ROOT / "tests" / "e2e"
NODE_MODULES = E2E_DIR / "node_modules"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_http(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_exc: Exception | None = None
    while time.time() < deadline:
        try:
            # Any HTTP response means the app is up; we don't care about status.
            httpx.get(url, timeout=1.0)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(0.2)
    raise RuntimeError(f"Backend at {url} never came up: {last_exc}")


@pytest.mark.skipif(
    not NODE_MODULES.exists(),
    reason="Puppeteer not installed. Run: npm install --prefix tests/e2e",
)
def test_login_view_hides_after_sign_in_for_both_roles(tmp_path):
    port = _free_port()
    db_path = tmp_path / "e2e.sqlite3"

    env = os.environ.copy()
    env["MJS_DB_PATH"] = str(db_path)
    env.pop("MJS_SCHEDULER", None)

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "prototype.backend.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_http(f"http://127.0.0.1:{port}/api/auth/me", timeout=20.0)

        result = subprocess.run(
            ["node", "verify-login.mjs"],
            cwd=E2E_DIR,
            env={**env, "URL": f"http://127.0.0.1:{port}/"},
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            pytest.fail(
                "Puppeteer e2e failed.\n"
                f"--- stdout ---\n{result.stdout}\n"
                f"--- stderr ---\n{result.stderr}",
                pytrace=False,
            )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
