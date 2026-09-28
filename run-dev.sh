#!/usr/bin/env bash
# 一键启动开发环境：后端 FastAPI(8000) + 前端 Vite(5173, 已配置 /api 代理)
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

export SCENE_STORE_DIR="${SCENE_STORE_DIR:-$(pwd)/runtime/scenes}"
mkdir -p "$SCENE_STORE_DIR"

echo ">> 启动后端 http://127.0.0.1:8000 （场景 JSON 存于 $SCENE_STORE_DIR）"
$PY -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

cd frontend
if [ ! -d node_modules ]; then
  echo ">> 安装前端依赖"
  npm install
fi
echo ">> 启动前端 http://127.0.0.1:5173"
npm run dev
