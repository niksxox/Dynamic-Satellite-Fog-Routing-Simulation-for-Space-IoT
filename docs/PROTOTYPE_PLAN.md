# PROTOTYPE PLAN — "It works end to end" (build first)

**Goal:** One screen. ~120 satellites orbit on a dark world map. Ground stations send 8 traffic flows. Links appear/disappear as satellites move. Static vs Adaptive routing run side by side on the same network. You can **click a link to break it**, **drag a satellite**, and watch live metrics diverge.

**In scope:** orbit engine, topology, failures, congestion/latency model, Static + Adaptive routing, WebSocket streaming, 2D deck.gl map, live metrics, basic controls, demo hardening.
**Out of scope (MVP does these):** 3D globe, storms/eclipse, scenarios, benchmark charts, TLE import, add/remove nodes, story mode, Docker.

**Time budget:** ~9–11 agent-hours. If you are short on time, **P0–P7 is a complete demo**; P8 makes it safe.

**How to use:** Open a fresh agent session per phase. Paste the "Agent Rules" from SPEC.md §0, then the phase prompt. Don't start the next phase until the previous one's "Done when" checks pass.

| Phase | Owner | Name | Output you can see |
|---|---|---|---|
| P0 | 👥 Both | Scaffold & dev loop | Backend + frontend run with one command, WS connected |
| PC | 👥 Both | **Contract freeze** | `schemas.py` + `types.ts` agreed (30 min) |
| P1 | 🧑‍💻 P1 | Orbit engine | Printed sat positions, tests green |
| P2 | 🧑‍💻 P1 | Topology builder | Link counts + connectivity report |
| P3a–c | 🧑‍💻 P1 | Conditions, traffic, routing, metrics | Headless sim: Adaptive beats Static in numbers |
| P4 | 🧑‍💻 P1 | Engine loop + WebSocket API | Live frames streaming |
| PM | 🎨 P2 | **Mock server** | Fake-but-valid frames so the UI can be built now |
| P5 | 🎨 P2 | Frontend map + live data | Moving satellites + links on map |
| P6 | 🎨 P2 | Interactions | Click-to-fail, drag satellite, route overlays |
| P7 | 🎨 P2 | Dashboard + controls | Live metrics, sparklines, toggles |
| PI | 👥 Both | **Integration** | Real backend replaces the mock |
| P8 | 👥 Both | Demo hardening | Auto-demo, reconnect, replay fallback, rehearsal |

---|---|---|
| P0 | Scaffold & dev loop | Backend + frontend run with one command, WS connected |
| P1 | Orbit engine | Printed sat positions, tests green |
| P2 | Topology builder | Link counts + connectivity report |
| P3 | Conditions, traffic, routing, metrics | Headless sim: Adaptive beats Static in numbers |
| P4 | Engine loop + WebSocket API | Live frames streaming |
| P5 | Frontend map + live data | Moving satellites + links on map |
| P6 | Interactions | Click-to-fail, drag satellite, route overlays |
| P7 | Dashboard + controls | Live metrics, sparklines, toggles |
| P8 | Demo hardening | Auto-demo, reconnect, replay fallback, rehearsal |

---

## 👥 TEAM SPLIT — work in parallel (read this first)

**Person 1 = Backend / simulation** (folder `backend/`). **Person 2 = Frontend / UI** (folder `frontend/`).
The two tracks only meet at the WebSocket contract in `SPEC.md` §12, so you can build at the same time.

```
Time →  0:00 ──── 0:45 ──── (parallel) ─────────────────────────── ~6:00 ── ~7:00 ── ~8:00
Both   [P0 scaffold][PC contract]                                  [PI integrate][P8 harden]
P1     .............[P1 orbit][P2 topology][P3a][P3b][P3c][P4 API].
P2     .............[PM mock][P5 map][P6 interactions][P7 dashboard]
```

### Rules for working in parallel
1. **Separate folders.** P1 touches only `backend/`; P2 touches only `frontend/` (+ `scripts/mock_server.py`). Shared files: `docs/SPEC.md`, `backend/app/schemas.py`, `frontend/src/net/types.ts`, `docs/CONTRACT_CHANGES.md`.
2. **Branches:** `p1-backend` and `p2-frontend`, merge into `main` after each phase passes its "Done when".
3. **Contract changes** (new field/command): the person who needs it edits SPEC §12 + both type files in ONE commit, appends a line to `docs/CONTRACT_CHANGES.md` (date, what changed, who must react), and messages the other person. P2 updates the mock the same day.
4. **Sync points:** (a) end of PC: both type files identical; (b) when P1 finishes P4: P1 shows `python -m app.sim.headless` output + `scripts/ws_probe.py` stream, P2 shows the UI on the mock → then PI.
5. **If P1 finishes early:** start the MVP backend phases (M1–M4 in `MVP_PLAN.md`). **If P2 finishes early:** start M8 (design system).

### PC — Contract freeze (BOTH, 30 min, one agent session, then both pull)

```text
ROLE: Senior full-stack engineer. Read docs/SPEC.md sections 12 and 15.

TASK: Turn the WebSocket protocol into code, with no simulation logic.
1) backend/app/schemas.py: pydantic v2 models for Init, Frame, FlowEval, Metrics, SimEvent, Ack/Error, OrbitPreview, and one model per command (play, pause, reset, set_scale, set_weights, set_params, fail_link, restore_link, fail_sat, restore_sat, move_sat, move_gs, preview_orbit, set_flow_scale, add_flow, remove_flow) with a discriminated union on `cmd`.
2) frontend/src/net/types.ts: TypeScript types that mirror them field-for-field (same names, same optionality).
3) scripts/check_contract.py: loads a sample JSON frame (create docs/sample_frame.json by hand with 3 sats, 4 links, 2 flows) and validates it against schemas.py; also add a tiny TS check (npx tsc --noEmit) so a sample typed object compiles.
4) docs/CONTRACT_CHANGES.md with the first line "v1 contract frozen".
DONE WHEN: check_contract.py passes and tsc passes. Both people pull this commit before starting their phases.
```

### PM — Mock server (PERSON 2, 45 min, run before P5)

```text
ROLE: Senior full-stack engineer. Read docs/SPEC.md section 12 and backend/app/schemas.py.

TASK: Build scripts/mock_server.py (FastAPI + uvicorn, port 8000, path /ws, CORS for 5173) that lets the frontend be built with NO real simulator.
- On connect send `init`: 120 sats (12 planes), 10 ground stations (SPEC §8 coordinates), 8 flows.
- Send `frame` at 10 Hz: satellites move on fake circular inclined orbits (period ~5730 s, time_scale default 20, so t advances 2 sim-s per frame), lat/lon computed with simple spherical math, vlat/vlon in deg per WALL second, st=0.
- Links: ISL between each sat and its 2 in-plane neighbours + 1 cross-plane neighbour (k=0), GSLs for each station to its 3 nearest sats above 25 deg (k=1). rho random-walk 0.1–0.95, ms from distance, loss 0.001.
- Flows: adaptive and static paths = BFS shortest path over the current links (adaptive avoids links with rho>0.85); pdr/ms plausible; metrics objects plausible and smoothly changing; history not needed.
- Commands: fail_link (mark down for 40 s; static path through it => blackholed:true, pdr 0; adaptive reroutes after 1.5 s), restore_link, fail_sat, restore_sat, move_sat (re-seed that sat's orbit phase so it continues from the new lat/lon), move_gs, set_scale, play, pause, set_flow_scale, set_weights (accept, no effect). Reply ack. Emit events for failures/reroutes.
- It must validate every outgoing message with schemas.py (so the mock can't drift from the contract).
DO NOT: implement real orbital mechanics, topology rules, or routing costs.
DONE WHEN: ws_probe.py (or the browser) shows a stable 10 Hz stream and commands change the stream accordingly.
```

### PI — Integration (BOTH, ~1 h)

```text
ROLE: Senior full-stack engineer. Read docs/SPEC.md sections 12, 13, 16, 17 and docs/CONTRACT_CHANGES.md.
TASK: Switch the frontend from scripts/mock_server.py to the real backend (same port; stop the mock).
1) Run both; fix every contract mismatch by editing the SIDE THAT DRIFTED FROM SPEC §12 (log each fix in docs/CONTRACT_CHANGES.md).
2) Verify end to end: satellites move smoothly, links appear/disappear, click-fail a link on an active path -> static blackholes, adaptive reroutes; drag a satellite -> orbit re-phases without snap-back; metrics diverge; fps >= 50; tickMs < 80.
3) Fix performance issues found (frame size, layer re-creation). Write docs/INTEGRATION_NOTES.md listing what was fixed.
DONE WHEN: the six checks in (2) pass in a 5-minute soak test.
```

---

## P0 — Scaffold & dev loop (30–45 min)  ·  **👥 BOTH**

```text
ROLE: You are a senior full-stack engineer. Read docs/SPEC.md sections 2, 3, 14 first.

TASK: Create the monorepo "satroute" exactly as in SPEC §3 (only the folders/files needed for now).

BACKEND (backend/):
- requirements.txt: fastapi, uvicorn[standard], numpy, networkx, scipy, pydantic>=2, orjson, pytest, httpx.
- app/main.py: FastAPI app. GET /health -> {"ok":true}. WebSocket /ws that on connect sends {"type":"hello","msg":"satroute"} and then every 1s sends {"type":"tick","n":<int>}. Enable CORS for http://localhost:5173.
- app/sim/__init__.py, app/sim/constants.py with the constants from SPEC §4.
- tests/test_health.py using FastAPI TestClient.

FRONTEND (frontend/):
- Vite + React 18 + TypeScript (strict) + Tailwind. Dependencies: zustand, deck.gl 8.9.x (@deck.gl/core @deck.gl/layers @deck.gl/geo-layers @deck.gl/extensions @deck.gl/react), topojson-client, world-atlas, recharts, lucide-react, @fontsource/inter.
- vite.config.ts: dev server 5173, proxy /ws (ws: true) and /api to http://localhost:8000.
- src/net/socket.ts: a reconnecting WebSocket client (exponential backoff 0.5s→5s) exposing onMessage and send.
- src/App.tsx: dark page (SPEC §14 tokens as CSS variables in index.css) showing "SatRoute" title and a connection pill (green "Connected"/red "Offline") plus the last message received.

SCRIPTS: scripts/dev.sh starts uvicorn (port 8000, --reload) and `npm run dev` together (use & and trap to kill both). Add a root README with 3 commands to run it.
Add .gitignore (node_modules, __pycache__, .venv, dist).

DO NOT: add any simulation logic yet.
DONE WHEN: `./scripts/dev.sh` starts both; browser at :5173 shows green "Connected" and ticking messages; `pytest` passes; `npm run build` passes with zero TS errors.
```

---

## P1 — Orbit engine (1 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior simulation engineer. Read docs/SPEC.md sections 4, 5, 16.
NOTE (Person 1): you never need the frontend; verify with pytest and scripts/ws_probe.py only.

TASK: Implement backend/app/sim/orbit.py EXACTLY per SPEC §5 (copy the reference code, then improve naming/docs where useful, but keep the math): Constellation dataclass, walker_delta, propagate_eci, eci_to_ecef, positions_ecef, ecef_to_latlon, latlon_to_ecef, rephase_to, ground_track.

TESTS (backend/tests/test_orbit.py), all must pass:
1. walker_delta(120,12,1,53,550) -> 120 sats, 12 planes x 10, all radius 6921 km at any t.
2. Period: sat position at t=0 and t=2*pi/n is identical (ECI) within 1e-6 km; period is between 5700 and 5760 s.
3. Speed from finite difference (ECI, 1 s step) is between 7.5 and 7.7 km/s.
4. max |latitude| over a full orbit for any sat <= 53.001 deg.
5. Ground-track drift: after one orbital period, ECEF longitude of a sat is ~ -(OMEGA_E*period) rad (~ -23.9 deg) from the start (within 0.1 deg).
6. Minimum pairwise distance between all 120 sats at t=0 and t=1000 is > 500 km.
7. rephase_to: for 50 random (lat in [-52,52], lon in [-180,180], t in [0,6000]) and random sat index, after rephase_to the sat's ECEF lat/lon at t equals the target within 0.01 deg, radius unchanged, and the direction of travel (sign of dz/dt) is the same as before the call.
8. rephase_to with |lat|=60 raises inclination to 60 deg and still lands on target.
9. latlon_to_ecef -> ecef_to_latlon round-trip within 1e-9.

ALSO: backend/app/sim/demo_orbit.py (python -m app.sim.demo_orbit) printing lat/lon/alt of the first 5 sats at t=0 and t=600.

DO NOT: write topology, routing, or API code.
DONE WHEN: pytest -q shows all tests green; paste the demo output.
```

---

## P2 — Topology builder (1 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior network/simulation engineer. Read docs/SPEC.md sections 6, 15, 16.

TASK: Implement backend/app/sim/topology.py per SPEC §6.
- Dataclasses: GroundStation(id:int, name:str, lat:float, lon:float, ecef:np.ndarray), TopoParams (from SPEC §15 isl/gsl), Topology(isl: list[tuple[int,int]], gsl: list[tuple[int,int]], pos: np.ndarray (N,3), ground_pos: np.ndarray, dist: dict[tuple[int,int], float]).
- default_ground_stations() returning the 10 stations in SPEC §8 with node ids N..N+9 (parameter n_sats).
- los_clear(), elevation_deg() exactly as in SPEC.
- build_topology(sat_pos, ground, prev: Topology|None, params) -> Topology implementing: all-pairs vectorised distance, LOS filter, greedy ISL selection with hysteresis (keep valid previous links first, then add new links under isl_build_frac, degree cap), GSL selection with top-K elevation and drop margin hysteresis. Keep link keys normalised as (min,max).
- Vectorise with NumPy; only the final greedy loops may be Python. Must run < 10 ms for 120 sats + 10 stations.

TESTS (tests/test_topology.py):
1. Two sats on opposite sides of Earth: LOS false. Two adjacent sats: LOS true.
2. No ISL longer than 5000 km; no node degree > 4; no duplicate links.
3. Hysteresis: build at t, then at t+2 s -> >= 95% of links identical (no flapping).
4. GSL: every GSL has elevation >= 23 deg (25 - margin); each ground station has <= 3 GSLs.
5. Dragged satellite (call rephase_to on one sat) still gets ISLs (no grid assumption).
6. Timing test: build_topology < 10 ms average over 100 calls (print the number).

SCRIPT: python -m app.sim.demo_topology — sample every 30 s over one orbit (0..5730 s) and print: avg ISL count, avg degree, min/avg number of visible sats per ground station, and the percentage of samples where each ground-station pair is connected in the NetworkX graph (ISL+GSL), plus the overall minimum.
If overall pair-connectivity < 95%, tune in this order and re-run: max_deg 4->5, isl_max_range 5000->5200 with ATMOS_KM 80->50, el_min 25->20. Report the final values you chose and update SPEC §15 numbers.

DONE WHEN: tests green and demo prints connectivity >= 95% for all pairs. Paste the table.
```

---

## P3 — Conditions, traffic, routing, metrics (2.5 h; run as THREE sessions: P3a, P3b, P3c)  ·  **🧑‍💻 PERSON 1 · Backend**

### P3a — Conditions + traffic evaluator

```text
ROLE: Senior simulation engineer. Read docs/SPEC.md sections 7, 8, 10.

TASK: Implement
1) backend/app/sim/conditions.py
   - LinkId = tuple[int,int] (min,max).
   - class ConditionModel(rng, params): persistent dicts keyed by LinkId: down_until[t], last_fail_t. Methods:
     step(topo, t, dt) -> list[SimEvent]: random failures (prob 1-exp(-dt/(MTBF/intensity)) per UP link), recoveries (t >= down_until), returns events {kind:'link_fail'|'link_restore', msg:'Link S014-S022 failed (random)'}.
     fail_link(a,b,t,duration|None), restore_link(a,b), fail_node(i), restore_node(i) (node failure = all adjacent links down; track failed_nodes set).
     is_up(a,b,t) -> bool.
     link_props(topo, a, b) -> dict(dist_km, prop_ms, capacity_mbps, kind) using SPEC §7 (ISL 2000, GSL 1000).
   - risk(a,b,t): loss_term and recent_fail_term per SPEC §7 (expiry_term = 0 for now).
   - Pure helper functions: queue_ms(rho), cong_loss(rho), survive(rho, base=0.001, weather=0.0), link_latency_ms(prop_ms, rho).
2) backend/app/sim/traffic.py
   - Flow dataclass, default_flows(ground) from SPEC §8.
   - evaluate(topo, cond, flows, paths: dict[flow_id, list[tuple[path:list[int], mbps:float]]], t) -> EvalResult with: per-link load/rho/ms/loss dicts, per-flow FlowEval(paths, ms, pdr, blackholed, delivered_mbps), totals (latMs weighted, pdr, thrMbps). Implement the 5 steps in SPEC §8 exactly. A path hop that is not in topo (physically gone) OR is down => chunk blackholed.

TESTS: formula tests (queue_ms(0)=0, rises, capped at 200; cong_loss 0 below 0.85; overload scaling), a 3-node line topology where load 1.5x capacity yields delivered = capacity*survive; blackholing when a hop is down; failure persistence across link disappearance/reappearance; deterministic with the same seed.

DONE WHEN: pytest green. Do not write routing yet.
```

### P3b — Static + Adaptive routing

```text
ROLE: Senior routing/algorithms engineer. Read docs/SPEC.md sections 9, 7 (risk), 8.

TASK: Implement backend/app/sim/routing/{cost.py,static.py,adaptive.py}.
- cost.py: link_cost(lat_ms, rho, risk, w) exactly per SPEC §9.1.
- static.py: class StaticRouter with state {flow_id: path}. update(topo, flows) -> dict[flow_id, [(path, mbps)]]. Graph = all physical links (topo.isl + topo.gsl) with weight = distance km; add virtual source/target handling by using the ground station node ids directly. Compute path only when missing or when any hop is no longer in topo. NEVER consider failures/congestion. Return a single chunk per flow with the full mbps. Provide reroute counter increments when the path changes.
- adaptive.py: class AdaptiveRouter(params). update(topo, cond, flows, t, loads_prev) -> routes. Steps: build nx.Graph of UP links known to the router (apply detect_delay: a link that failed less than detect_delay_s ago is still treated as up, which will blackhole traffic until detection), set edge attr 'w' using link_cost with that router's own running load (start from zero each cycle), run incremental load assignment from SPEC §9.3 with `chunks`=4, stickiness 0.9 on previous edges, merge identical chunk paths, refresh 'w' only on touched edges. Return routes + count reroutes (primary = largest chunk path changed). Handle unreachable (no path): return empty list -> flow blackholed.
- A tiny `routing/__init__.py` exposing both classes.

TESTS (tests/test_routing.py) on a hand-built topology/mock:
1. Diamond graph S->A->D and S->B->D, equal distance: adaptive with a 1500 Mbps flow (links 1000 Mbps) splits across both paths; static uses one and delivers <= 1000*survive.
2. Fail link S-A: static blackholes (pdr 0); adaptive after detect_delay reroutes via B and pdr recovers; time-to-recover measured ~ detect_delay (+ one tick).
3. Hysteresis: tiny cost noise does not cause reroutes (0 reroutes over 100 steps).
4. Congestion avoidance: with a loaded shorter path adaptive prefers the longer uncongested path.
5. Unreachable destination handled gracefully.
6. Performance: adaptive.update on the real default topology (120 sats, 10 GS, 8 flows) < 60 ms (print p95 over 50 runs).

DONE WHEN: all tests green; paste perf numbers.
```

### P3c — Metrics + headless engine

```text
ROLE: Senior simulation engineer. Read docs/SPEC.md sections 10, 11, 15, 16.

TASK:
1) backend/app/sim/metrics.py: MetricsTracker per algorithm implementing SPEC §10: EWMA latency, PDR, throughput, reroute count + per-minute rate (sim-time window), outage episode tracking per flow (start when delivered==0, end when >0, store durations -> recoverS = mean of completed episodes, also count ongoing), rolling 120-point history. Network-level: link uptime and active failures.
2) backend/app/sim/engine.py: class Engine(config, seed) implementing the SPEC §11 tick exactly with methods: step(dt_wall) -> Frame dict (SPEC §12 shape, as python dicts), apply_command(cmd) for: play, pause, reset, set_scale, set_weights, fail_link, restore_link, fail_sat, restore_sat, move_sat, move_gs, set_flow_scale, set_params. Include sat velocity (vlat,vlon deg per WALL second: finite difference of positions at t and t+1 sim-s times time_scale, lon wrapped to [-180,180)). Events accumulate and are returned once. Include tickMs measurement.
3) engine.run_headless(duration_s, seed, scale_dt=2.0) -> summary dict {adaptive:{...}, static:{...}}, and a script `python -m app.sim.headless` that runs 1800 sim-s with seed 42 and prints a comparison table (latency, PDR, throughput, reroutes, recovery time, link uptime, failure count) plus tick-time p95.

TESTS: determinism (same seed => identical summary), frame schema keys, command effects (fail_link causes static blackhole for that flow if on path).

ACCEPTANCE (SPEC §16): in the headless run Adaptive PDR > Static PDR; Adaptive recovery < 5 s; Static recovery > 20 s; p95 tick < 80 ms. If not met, debug the simulation (cost weights, detection delay, failure rates, capacities) — do NOT hard-code results. Document any parameter changes in SPEC §15.

DONE WHEN: the headless table is printed and meets acceptance.
```

---

## P4 — Engine loop + WebSocket API (1 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior backend engineer. Read docs/SPEC.md sections 11, 12.

TASK: Wire the Engine into FastAPI (backend/app/main.py, app/schemas.py).
- One global Engine created at startup (lifespan). An asyncio background task runs the loop at 10 Hz (use time.perf_counter drift correction: sleep(max(0, next_tick - now))). Run engine.step in the loop thread directly (it is < 80 ms).
- WebSocket /ws: on connect send {"type":"init", ...} (config, ground stations with names, flows, nSats, plane per sat). Then broadcast every frame to all connected clients (a ConnectionManager; drop dead sockets; if a client is slow, skip frames for it rather than queueing). Serialise with orjson.
- Incoming messages {type:'cmd', cmd, args, id?}: validate with pydantic models per command; call engine.apply_command; reply {type:'ack', id} or {type:'error', msg}. A failed command must never crash the loop.
- REST: GET /api/state (single frame snapshot), POST /api/reset.
- Use the existing schemas.py (frozen in PC) for validation.
- schemas.py and frontend/src/net/types.ts were frozen in step PC: do NOT redesign them. If the real engine needs a change, follow the contract-change rule (edit SPEC §12 + both files in one commit + docs/CONTRACT_CHANGES.md).

TESTS: Starlette TestClient websocket: receive init then >=5 frames within 2 s; frame has sats(120), links, flows(8), metrics; send fail_link and receive ack + an event of kind link_fail in a later frame; invalid command returns error and the stream continues.

MANUAL CHECK: use `websocat` or a small python client script (scripts/ws_probe.py) printing t, tickMs, number of links per frame for 10 s.

DONE WHEN: probe shows stable 10 Hz frames, tickMs < 80, frame size printed (< 40 KB).
```

---

## P5 — Frontend map + live data (1.5 h)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Senior frontend engineer (React, TypeScript, deck.gl). Read docs/SPEC.md sections 12, 13, 14.
NOTE (Person 2): build and test against scripts/mock_server.py (step PM); do not wait for the real backend.

TASK: Build the live map.
1) store/useSim.ts (Zustand): init, latestFrame, prevFrame, recvAt (performance.now), connected, ui: {view:'adaptive'|'static'|'compare', selection:null, dragging:null}. socket.ts feeds the store on init/frame messages.
2) map/interpolate.ts: function satPositionsAt(now) implementing SPEC §13 extrapolation with shortest-arc longitude wrap, clamped to 300 ms.
3) map/MapView.tsx: DeckGL with MapView (no basemap), initialViewState {longitude:10, latitude:20, zoom:1.3, minZoom:1, maxZoom:6}, controller enabled. rAF loop re-renders layers using interpolated positions. Layers per SPEC §13 for now: ocean background (ScatterplotLayer not needed — use deck.gl `style` with the --bg colour), land GeoJsonLayer from world-atlas countries-110m via topojson-client (fill #12284d, stroke #24426e, lineWidthMinPixels 0.5), ISL/GSL LineLayer (colour by rho: <0.5 teal rgba(79,195,217,150), 0.5–0.85 amber, >0.85 red; down links rgba(229,72,77,120)), ground stations (orange dots + TextLayer names), satellites (white dots radius ~4 px with teal halo; later icons). Use `wrapLongitude: true` or split segments at the antimeridian via lib/geo.ts so no line crosses the whole map.
4) App layout: top bar with tabs (Network View | Controls | Performance | Logs — only Network View functional), status pill, sim clock "T+mm:ss"; map takes the remaining space; a right panel placeholder "Live Metrics" showing raw numbers (latency, PDR, throughput, reroutes) for adaptive and static.
5) Performance: memoise layer data, use updateTriggers, never allocate big arrays per frame unnecessarily (typed arrays for positions if needed). Show an FPS counter in the corner (dev only).

DONE WHEN: with the backend running you see 120 satellites gliding smoothly (no jitter at 10 Hz source), links appearing/disappearing, links with no antimeridian streaks, >= 50 fps, metrics numbers updating. Take a screenshot to confirm.
```

---

## P6 — Interactions: fail, drag, route overlays (1.5 h)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Senior frontend engineer (deck.gl interaction). Read docs/SPEC.md sections 12, 13 (Dragging, Inspector) and 17 pitfalls 1–2.
NOTE (Person 2): build and test against scripts/mock_server.py (step PM); do not wait for the real backend.

TASK:
1) Picking: make satellites, ground stations, and links pickable (links with pickingRadius/ widthMinPixels 6). Hover -> tooltip (sat id/plane/alt/lat/lon, link kind/length/latency/util, GS name). Click -> ui.selection, opening map/Inspector.tsx (right-bottom card).
2) Inspector actions: link -> "Fail link" / "Restore link"; satellite -> "Fail satellite"/"Restore"; sends commands via the socket. A failed link/sat renders red dashed/dim; a toast appears from backend events.
3) Drag satellite per SPEC §13 "robust method": implement in map/drag.ts. Use a ref to the Deck instance; on pointerdown over a satellite call deck.setProps({controller:{dragPan:false, dragRotate:false}}) synchronously; on pointermove unproject to lon/lat and draw the dragged satellite at the cursor (local override); on pointerup send move_sat and restore the controller; 4-px click-vs-drag threshold; cursor changes (grab/grabbing). While dragging, show a faint ring at the cursor. After drop, the backend re-phases the orbit; the sat should continue from the new spot with no visual snap-back.
4) Drag ground stations the same way (move_gs).
5) Route overlay: a flows list in the Live Metrics panel; selecting a flow draws its adaptive path (teal, wide, solid) and static path (orange, dashed) as PathLayers following node positions (sat interpolated positions + ground positions); blackholed paths draw red. Handle paths crossing the antimeridian by splitting.
6) Keyboard: Esc clears selection, Space toggles play/pause, F fails the selected link.

DONE WHEN: (a) clicking a link on the teal path and pressing Fail turns Static red/blackholed and Adaptive path visibly changes within ~2 s; (b) dragging a satellite across the map works without the map panning, and the sat keeps orbiting from the drop point; (c) panning the map empty-space still works. Record a 20-second screen capture.
```

---

## P7 — Dashboard + controls (1 h)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Senior frontend engineer / UI designer. Read docs/SPEC.md sections 10, 14 and look at the deck slide "Simulator Features and Dashboard" for the target look.
NOTE (Person 2): build and test against scripts/mock_server.py (step PM); do not wait for the real backend.

TASK: Replace the placeholder panels with a polished dashboard.
1) panels/LiveMetrics.tsx: "Live Metrics" card for the selected view. Rows: End-to-end Latency (ms), Packet Delivery Ratio (%), Reroutes Performed, Link Uptime (%), Network Throughput (Gbps) — each with big tabular number + Recharts sparkline (last 120 points, no axes). In 'compare' view each row shows Adaptive (teal) vs Static (orange) values side by side plus a delta badge (e.g. "▼ 38% latency"). Colour PDR/uptime green/amber/red by thresholds. Smooth number transitions.
2) View toggle (Adaptive | Static | Compare) in the top bar; changes which routes/colours the map emphasises (compare = both overlays).
3) panels/Controls.tsx (compact, collapsible drawer on the left of the map for the prototype): Play/Pause, Reset, Speed slider (1×–120× with log scale), weights sliders a/b/c (0–3) sending set_weights, "Failure intensity" slider (0–10×), buttons: "Break random active link", "Break a satellite", "Flash crowd ×3" (set_flow_scale 3, toggles back), "Restore all".
4) Event feed: bottom-left overlay showing last 5 events (icon by level, fade after 8 s). Legend bar bottom (Active Route / Alternate Route / Satellite / Ground Station) and a status "All Systems Nominal" that turns amber/red when activeFailures > 0 / PDR < 90%.
5) Visual polish pass per SPEC §14: Inter font, panel styling, subtle glow on the teal elements, no layout shift as numbers change.

DONE WHEN: the screen looks like a command-centre dashboard; every control works; compare view clearly shows Adaptive winning after a failure/flash crowd.
```

---

## P8 — Demo hardening (1 h)  ·  **👥 BOTH**

```text
ROLE: Senior engineer focused on reliability for a live demo. Read docs/SPEC.md section 1 (judging moments), 16, 17.

TASK:
1) Auto-demo button ("▶ Run Demo", top bar): a scripted 75-second sequence driven from the frontend that calls existing commands with on-screen captions: [0s] calm, select DEL→LON flow, view=Compare; [10s] fail a link on its active path (caption "Link failure on active path"); [20s] restore, flash crowd ×3 (caption "Traffic surge"); [35s] drag one satellite to a new location programmatically via move_sat (caption "Constellation reconfigured"); [50s] break a satellite; [65s] wrap-up caption with final deltas. Cancellable with Esc.
2) Resilience: socket auto-reconnect with "Reconnecting…" banner; React ErrorBoundary around the map; if the backend sends an error, show a toast; never crash.
3) Replay fallback: backend script `python -m app.sim.record --seconds 120 --out frontend/public/replay.json` records frames; frontend has `?replay=1` mode that plays them from file with the same UI (so a dead backend/laptop issue does not kill the demo).
4) Performance: verify 60 fps target with 120 sats on a mid laptop; fix any layer re-creation hot spots; verify no memory growth over 10 minutes (frame buffers bounded).
5) Docs: README with 1-command run, screenshots placeholder, and `docs/DEMO_SCRIPT.md` containing a 3-minute pitch script that maps each judging moment to what to click and what to say, and a list of 8 likely judge questions with 2-sentence answers (why adaptive beats static, how the cost function works, how drag re-phases the orbit, limits of the model, how it scales, what real data could plug in).
6) Replace nothing in the numbers by hand: add a small "How these numbers are computed" tooltip on the metrics panel.

DONE WHEN: a cold start -> run demo -> finish works 3 times in a row without touching the keyboard; `?replay=1` works with the backend stopped.
```

---

## Prototype Definition of Done (checklist)

- [ ] Satellites orbit smoothly on a dark map with live links
- [ ] 8 flows routed by Static and Adaptive on the same network
- [ ] Click-to-fail and drag-to-move both work and visibly change routing
- [ ] Live metrics + sparklines + compare view
- [ ] Headless run proves Adaptive > Static with real numbers
- [ ] Auto-demo + replay fallback + demo script ready

## Who signs off what
- **Person 1:** headless table (P3c), frame stream stats (P4), tests green.
- **Person 2:** 60 fps screen capture, click-fail + drag capture (P6), dashboard screenshot (P7).
- **Both:** PI soak test, P8 three clean demo runs.
