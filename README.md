# SatRoute — Intelligent Routing for Dynamic Satellite Networks

A live, interactive LEO constellation simulator where you can watch data routed across moving satellites, break things (links, satellites, whole regions, weather), drag satellites around, and watch an **Adaptive cost-aware router** beat a **Static shortest-path baseline** with real, measured numbers.

## Quick Start (3 Commands)

```bash
# 1. Setup Python virtual environment & backend dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. Install frontend dependencies
cd frontend && npm install && cd ..

# 3. Start both Backend & Frontend
./scripts/dev.sh
```

- **Frontend App**: [http://localhost:5173](http://localhost:5173)
- **Backend API & Health**: [http://localhost:8000/health](http://localhost:8000/health)
- **WebSocket Endpoint**: `ws://localhost:8000/ws`

## Architecture & Plans
- [docs/SPEC.md](docs/SPEC.md) — Technical Specification & Contract
- [docs/PROTOTYPE_PLAN.md](docs/PROTOTYPE_PLAN.md) — Prototype Implementation Plan (P0–P8)
- [docs/MVP_PLAN.md](docs/MVP_PLAN.md) — MVP Implementation Plan (M0–M14)
