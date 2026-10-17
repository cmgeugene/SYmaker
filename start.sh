#!/bin/zsh
# SYmaker 실행: 프론트엔드를 빌드하고 백엔드 서버(http://127.0.0.1:8765)를 띄운다.
set -e
cd "$(dirname "$0")"
if [ ! -d frontend/node_modules ]; then (cd frontend && npm install); fi
(cd frontend && npm run build)
cd backend
uv sync -q
echo "\n▶ http://127.0.0.1:8765 에서 SYmaker가 열립니다.\n"
(sleep 2 && open http://127.0.0.1:8765) &
exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8765
