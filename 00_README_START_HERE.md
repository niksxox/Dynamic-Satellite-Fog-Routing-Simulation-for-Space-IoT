# SatRoute — Hackathon Master Plan (start here)

## What's in this folder
| File | Purpose |
|---|---|
| `SPEC.md` | The technical contract: architecture, orbit math, topology rules, cost function, routing algorithms, WebSocket protocol, design tokens. **Copy into your repo as `docs/SPEC.md`.** The agent reads this before every phase. |
| `PROTOTYPE_PLAN.md` | Phases P0–P8. A complete working demo: live map, Static vs Adaptive routing, click-to-fail, drag satellites, metrics. |
| `MVP_PLAN.md` | Phases M0–M14. The winning version: scenarios, storms, eclipse, predictive routing, benchmarks, 3D globe, story mode, Docker, pitch kit. |

## Two-person split (built into both plans)
- **Person 1 = Backend/simulation** (`backend/`): Prototype P1–P4, MVP M1–M7.
- **Person 2 = Frontend/UI** (`frontend/`): Prototype PM (mock server) + P5–P7, MVP M8–M13.
- **Together:** P0, PC (contract freeze), PI (integration), P8, MVP M0 and M14.
- Person 2 builds against `scripts/mock_server.py`, so nobody waits. Each plan has a "TEAM SPLIT" section with the timeline, sync points, branch rules and the prompts for the contract freeze, mock server and integration.

## Recommended order
1. Put all three files in `docs/` of a new repo (`satroute/`).
2. Do the **Prototype** first (P0 → P8). After P7 you already have a demoable product.
3. Continue with the **MVP** phases in the priority order listed at the top of `MVP_PLAN.md`.
4. Always finish with **M14** (QA, packaging, pitch kit).

## How to run each phase with your coding agent
1. Open a fresh session.
2. Paste the "Agent Rules" from `SPEC.md` §0.
3. Paste ONE phase prompt (the fenced block).
4. Verify the "Done when" line yourself. Only then move on.

Small phases = fewer mess-ups. If an agent goes off track, discard the session and re-run that phase.

## Key design decisions (already made for you)
- **Server-authoritative simulation** in Python (NumPy + NetworkX), streamed over WebSocket at 10 Hz; the browser interpolates at 60 fps.
- **deck.gl 2D map with bundled country shapes**: smooth with 100+ moving satellites, no internet or map tiles needed at the venue.
- **Dragging a satellite re-fits its orbit** (SPEC §5 `rephase_to`), so it keeps orbiting from the drop point and the topology and routes recompute live.
- **Fair comparison**: Static and Adaptive run on the same physical network, each with its own load accounting.
- **Default constellation 120 sats (12 planes × 10)**: a 6×8 constellation would not stay connected with realistic line-of-sight limits.

## Things to fix in your deck
- **Slide 8 numbers must come from real benchmark runs** (MVP phase M6). Judges often ask how they were measured, and the answer "our simulator, 5 seeds, mean ± std" is a strong one.
- Replace the slide 7 mock-up with a real screenshot of the app.
- Slide 5's three-row table (Static / Dijkstra on Live Graph / Adaptive) is exactly what the M6 three-way benchmark produces.

## The 5 moments to build the pitch around
1. Satellites orbiting, links appearing and disappearing.
2. Break a link on the active path: Static dies, Adaptive reroutes in about 2 s.
3. Drag a satellite: orbit and impact preview, routes adapt.
4. Flash-crowd congestion: Adaptive splits traffic, Static melts.
5. Benchmark charts from real runs.

## Honest limitations to state in the pitch
Circular orbits without J2, a fluid-flow traffic model (not packet-level), simplified weather and eclipse models. Say it before the judges do; it makes the rest more credible.
