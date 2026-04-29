#!/usr/bin/env bash
# Convenience launcher. Run from the repo root.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 -m uvicorn prototype.backend.main:app \
  --host 127.0.0.1 --port 8765 --reload
