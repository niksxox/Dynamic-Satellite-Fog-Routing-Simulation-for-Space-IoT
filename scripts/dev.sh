#!/usr/bin/env bash
set -e

# Cleanup children on exit
trap 'kill $(jobs -p) 2>/dev/null || true' EXIT SIGINT SIGTERM

echo "Starting SatRoute Backend (FastAPI :8000)..."
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

PYTHONPATH=backend uvicorn app.main:app --port 8000 --reload &

echo "Starting SatRoute Frontend (Vite :5173)..."
cd frontend
npm run dev &

wait
