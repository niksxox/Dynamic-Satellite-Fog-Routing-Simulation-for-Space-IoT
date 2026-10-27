# SatRoute — Intelligent Routing for Dynamic Satellite Networks

A live, interactive LEO constellation simulator where you can watch data routed across moving satellites, break things (links, satellites, whole regions, weather), drag satellites around, and watch an **Adaptive cost-aware router** beat a **Static shortest-path baseline** with real, measured numbers.

## Quick Start (Windows)

```powershell
# 1. Setup Python virtual environment & backend dependencies
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. Install frontend dependencies
npm --prefix frontend ci

# 3. Start each service in a separate PowerShell terminal from the project root.
# Backend terminal:
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Frontend terminal:
npm --prefix frontend run dev
```

- **Frontend App**: [http://localhost:5173](http://localhost:5173)
- **Backend API & Health**: [http://localhost:8000/health](http://localhost:8000/health)
- **WebSocket Endpoint**: `ws://localhost:8000/ws`
- The Vite development server proxies `/ws` and `/api` to the backend on port 8000.

## Read-only satellite tracking

The map offers **Simulation**, **Live TLE**, and **Combined** position modes. Live tracking first loads up to 120 Starlink orbital-element records from the public CelesTrak GP endpoint and propagates estimated Earth-fixed positions using SGP4. If CelesTrak is unavailable, the app falls back to the public [TLE API](https://tle.ivanstanojevic.me/api/tle/?search=STARLINK), keeps only Starlink elements no older than 48 hours, and reports which source is active. TLE feeds provide orbital estimates, not live spacecraft telemetry or operational satellite routes. The element set is refreshed no more often than every two hours; positions are recalculated continuously from that set. Click a tracked satellite to show a predicted one-orbit ground track.

The **Combined** view draws the simulator's generated links and routes over TLE-derived satellite positions. Those routes, failures, and dashboard metrics are still simulated; no operational traffic, onboard telemetry, or satellite-control commands are connected. TLEs provide estimates, not live onboard measurements or real satellite routing data. Internet access to a TLE provider is required; when both feeds are unavailable, the UI reports that state and the simulation mode remains available.

## Architecture & Plans
- [docs/SPEC.md](docs/SPEC.md) — Technical Specification & Contract
- [docs/PROTOTYPE_PLAN.md](docs/PROTOTYPE_PLAN.md) — Prototype Implementation Plan (P0–P8)
- [docs/MVP_PLAN.md](docs/MVP_PLAN.md) — MVP Implementation Plan (M0–M14)
