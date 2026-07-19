#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

cd "$ROOT/frontend"
if [ ! -d node_modules ]; then npm install; fi
npm run build

cd "$ROOT/backend"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -r requirements.txt
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
