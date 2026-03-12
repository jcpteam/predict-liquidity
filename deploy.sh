#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-2}"

echo "=== Prediction Market Liquidity Comparator - Deploy ==="

# ── 1. 前端构建 ──
echo "[1/4] Building frontend..."
cd "$PROJECT_DIR/frontend"
if ! command -v node &>/dev/null; then
  echo "Error: Node.js not found. Install Node.js 18+ first."
  exit 1
fi
npm ci --silent
npm run build
echo "  ✓ Frontend built → frontend/dist/"

# ── 2. 后端依赖 ──
echo "[2/4] Setting up backend..."
cd "$PROJECT_DIR/backend"
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
pip install -q gunicorn uvloop httptools

# ── 3. 环境变量 ──
echo "[3/4] Checking environment..."
if [ ! -f "$PROJECT_DIR/backend/.env" ]; then
  if [ -f "$PROJECT_DIR/backend/.env.example" ]; then
    cp "$PROJECT_DIR/backend/.env.example" "$PROJECT_DIR/backend/.env"
    echo "  ⚠ Created .env from .env.example — please edit backend/.env with your API keys"
  fi
fi

# ── 4. 启动服务 ──
echo "[4/4] Starting server on port $PORT with $WORKERS workers..."
cd "$PROJECT_DIR/backend"
exec gunicorn main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "$WORKERS" \
  --bind "0.0.0.0:$PORT" \
  --access-logfile - \
  --error-logfile -
