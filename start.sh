#!/usr/bin/env bash
set -e

# ─── CFR Rates Regime Dashboard ─── Launcher ───
# Usage: ./start.sh [--fred-key YOUR_KEY] [--port 8000]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8000
FRED_KEY=""

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fred-key) FRED_KEY="$2"; shift 2 ;;
    --port)     PORT="$2"; shift 2 ;;
    -h|--help)
      echo "CFR Rates Regime Dashboard"
      echo ""
      echo "Usage: ./start.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --fred-key KEY   Set your FRED API key (or set FRED_API_KEY env var)"
      echo "  --port PORT      Server port (default: 8000)"
      echo "  -h, --help       Show this help"
      echo ""
      echo "Get a free FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Use env var if flag not provided
FRED_KEY="${FRED_KEY:-$FRED_API_KEY}"

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   CFR RATES REGIME DASHBOARD v1.0            ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ─── Step 1: Check Python venv ───
VENV_DIR="$SCRIPT_DIR/backend/venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "  [1/3] Creating Python virtual environment..."
  python3 -m venv "$VENV_DIR"
  echo "  [1/3] Installing Python dependencies..."
  "$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/backend/requirements.txt"
else
  echo "  [1/3] Python environment ready"
fi

# ─── Step 2: Build frontend if needed ───
DIST_DIR="$SCRIPT_DIR/frontend/dist"
if [ ! -f "$DIST_DIR/index.html" ]; then
  echo "  [2/3] Building frontend..."
  cd "$SCRIPT_DIR/frontend"
  if [ ! -d "node_modules" ]; then
    npm install --silent
  fi
  npx vite build --silent 2>/dev/null || npx vite build
  cd "$SCRIPT_DIR"
else
  echo "  [2/3] Frontend build ready"
fi

# ─── Step 3: Start server ───
echo "  [3/3] Starting server on http://localhost:$PORT"
echo ""

if [ -n "$FRED_KEY" ]; then
  echo "  FRED API key: configured"
else
  echo "  FRED API key: not set (enter it in the app or use --fred-key)"
fi

echo ""
echo "  → Open http://localhost:$PORT in your browser"
echo "  → Press Ctrl+C to stop"
echo ""

export FRED_API_KEY="$FRED_KEY"
exec "$VENV_DIR/bin/python" -m uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --log-level warning
