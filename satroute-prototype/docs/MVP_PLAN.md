# MVP PLAN — "The version that wins" (build on top of the prototype)

**Goal:** A product-grade simulator with every feature promised in the slides and the "wow" extras judges remember: scenarios, weather storms, eclipse, predictive routing, congestion splitting, add/pin/drag satellites with live orbit preview, 3D globe mode, benchmark charts from real runs, logs, controls, story mode.

**Relationship to the prototype:** Same architecture (SPEC.md). The MVP **extends** the prototype codebase; the phases below say which prototype files they modify. If you skipped the prototype, do PROTOTYPE_PLAN P0–P5 first (they are the foundation), then continue here.

**Time budget:** ~20–26 agent-hours. Priority order if time runs out (cut from the bottom): M0 → M4 → M5 → M6 → M10 → M11 → M9 → M13 → M3 → M2 → M1 → M12 → M14 (M14 is always last and always done).

| Phase | Owner | Name | What judges see | Needs |
|---|---|---|---|---|
| M0 | 👥 Both | Audit, config, test/CI base | Clean, tested foundation | prototype done |
| M1 | 🧑‍💻 P1 | Orbit v2 | Add/pin/remove sats, TLE option, ground-track preview | M0 |
| M2 | 🧑‍💻 P1 | Topology v2 + node/plane failures | Kill an entire orbital plane | M1 |
| M3 | 🧑‍💻 P1 | Conditions v2 | Storm cells, eclipse derating, flash crowds | M2 |
| M4 | 🧑‍💻 P1 | Routing v2 | Predictive routing, splitting, "why this path" | M3 |
| M5 | 🧑‍💻 P1 | Scenario engine | One-click disaster scenarios | M4 |
| M6 | 🧑‍💻 P1 | Benchmark runner | Real charts replacing slide 8 | M4 |
| M7 | 🧑‍💻 P1 | Protocol hardening | Fast, robust streaming | M5 |
| M8 | 🎨 P2 | Frontend design system | Pro layout, panels, theming | M0 |
| M9 | 🎨 P2 | Map v2 | Footprints, trails, day/night, packet particles | M8 |
| M10 | 🎨 P2 | Interaction v2 | Drag with live orbit preview, add/pin/remove | M9 + P1's M1 contract |
| M11 | 🎨 P2 | Controls + Performance + Logs tabs | The full dashboard from the slides | M8 + P1's M5/M6 contract |
| M12 | 🎨 P2 | 3D globe mode | Cinematic globe view | M9 |
| M13 | 🎨 P2 | Story mode + compare split | Self-running guided demo | M11 |
| M14 | 👥 Both | QA, packaging, pitch kit | Docker, README, demo script, slide updates | everything |

## 👥 TEAM SPLIT — work in parallel (read this first)

**Person 1 = Backend / simulation** (`backend/`): M1 → M2 → M3 → M4 → then M5 and M6 (either order) → M7.
**Person 2 = Frontend / UI** (`frontend/`): M8 → M9 → M10 → M11 → M12 → M13.
**Both:** M0 first (together), M14 last (together).

```
Time →   0 ─ 0:45 ───────────────────────────────────────────────── ~20h ──── +3h
Both    [M0]                                                                  [M14]
P1       [M1 orbit][M2 topo][M3 cond][M4 routing][M5 scen][M6 bench][M7 proto]
P2       [M8 design][M9 map][M10 interact][M11 tabs][M12 3D][M13 story]
Syncs:        S1(M1 done)      S2(M4)        S3(M5+M6 done)
```

### Dependency handoffs (the only places one person waits for the other)
| Sync | When | P1 delivers | P2 uses it for |
|---|---|---|---|
| **S1** | M1 done | commands `add_sat`, `remove_sat`, `pin_sat`, `preview_orbit` (+ `orbit_preview` message) in SPEC §12 | M10 drag preview, add/pin/remove |
| **S2** | M4 done | `explain`, proactive/reactive reroute counters, weight presets in frames | M9 particles, M11 Controls/Performance |
| **S3** | M5 + M6 done | `/api/scenarios`, `load_scenario`, `/api/benchmark` + exports | M11 Scenarios/Benchmark UI, M13 story mode |

**Before each sync P1 does this (15 min, mandatory):** update SPEC §12, `schemas.py`, `types.ts` and `docs/CONTRACT_CHANGES.md` for the new fields/commands, and push a **mock-ready sample message** into `docs/samples/`. P2 then extends `scripts/mock_server.py` (prompt below) so UI work never blocks on real backend code.

If P2 reaches a phase whose sync isn't ready, P2 builds it against the mock. If P1 gets ahead, P1 can help with the benchmark UI wiring (M11 part 2) or pre-record replays (M13 step 4).

### Rules
1. **Separate folders:** P1 → `backend/`; P2 → `frontend/` + `scripts/mock_server.py`. Shared: `docs/SPEC.md`, `schemas.py`, `types.ts`, `docs/CONTRACT_CHANGES.md`, `docs/samples/`.
2. **Branches:** `p1-backend`, `p2-frontend`; merge to `main` after each phase passes "Done when"; tag `sync-1/2/3` on main when a sync is delivered.
3. **Contract change = one commit** touching SPEC §12 + both type files + CONTRACT_CHANGES.md, announced to the other person immediately.
4. **Integration check after every sync (20 min, both):** run the real backend with the real frontend and confirm the new feature end to end before continuing.

### MS — Extend the mock for a sync (PERSON 2, ~20 min, repeat at S1, S2, S3)

```text
ROLE: Senior full-stack engineer. Read docs/CONTRACT_CHANGES.md (latest entries), docs/SPEC.md §12 and docs/samples/.

TASK: Update scripts/mock_server.py so it supports the newly frozen contract pieces, validating every outgoing message with backend/app/schemas.py.
- S1: add_sat / remove_sat / pin_sat / preview_orbit (return a fake 190-point ground track starting at the target plus inc_deg and period_s), preview_impact (random plausible latencyDeltaMs/affectedFlows).
- S2: frames carry flows[i].adaptive.explain {reason, detail, chosen_cost, alt_cost}, metrics.proactiveReroutes/reactiveReroutes/avgStretch; set_weights presets change the fake paths a little.
- S3: GET /api/scenarios (6 titles), load_scenario (frames include scenario progress), POST /api/benchmark + GET /api/benchmark/{id} returning plausible three-way results (static / liveDijkstra / adaptive, mean and std) after a fake 5-second progress.
DO NOT implement real simulation logic.
DONE WHEN: the new UI features can be built and demoed fully against the mock.
```

Use the same session discipline as the prototype: one phase per fresh agent session, paste SPEC §0 Agent Rules first, verify "Done when" before moving on.

---

## M0 — Audit, config, test/CI base (45 min)  ·  **👥 BOTH**

```text
ROLE: Staff engineer. Read docs/SPEC.md fully.
NOTE: Both people do M0 together in one session (one drives, one reviews), then split.

TASK:
1) Audit the existing code against SPEC. Produce docs/AUDIT.md listing deviations, dead code, TODOs, and any performance hot spots (measure p95 tick time and frontend fps). Fix only blockers.
2) Centralise configuration: backend/app/config.py with a pydantic `SimConfig` holding the SPEC §15 defaults; all sim modules read from it (no magic numbers). Add GET /api/config and POST /api/config (validated partial update that resets the engine safely).
3) Tooling: ruff + mypy (lenient) config for backend; eslint + prettier for frontend; `make test` (pytest + vitest) and `make dev`. Add vitest with one test for interpolate.ts (longitude wrap).
4) GitHub-Actions-style workflow file .github/workflows/ci.yml running both test suites (even if we don't use GitHub, keep it).
5) Seeded determinism: ensure every random call uses the engine's Generator.

DONE WHEN: `make test` green, AUDIT.md written, config endpoint works, no behaviour change in the running app.
```

---

## M1 — Orbit v2 (2 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior simulation engineer. Read docs/SPEC.md sections 5, 12.
NOTE (Person 1): any new command/field must be added to SPEC §12, schemas.py, types.ts and docs/CONTRACT_CHANGES.md in one commit, plus a sample message in docs/samples/.

TASK (modify backend/app/sim/orbit.py, engine.py, schemas.py):
1) Dynamic constellation editing in Engine.apply_command:
   - add_sat{lat,lon,inc_deg?=53,alt_km?=550}: append a new satellite whose orbit passes over (lat,lon) now (use rephase_to on a fresh entry; keep arrays consistent: plane id = -1 for user-added). Node indexing: ground stations must keep valid ids -> change ground node ids to be assigned as N_current+g on every topology build and keep a stable `gs_id` (0..G-1) for the API. Update all frames/commands to use gs_id for ground stations and a separate `node` field where paths need graph node ids. Update types.ts accordingly.
   - remove_sat{id}: mark removed (keep index stable, excluded from topology/frames) so ids do not shift.
   - pin_sat{id,pinned}: pinned sats freeze at their current ECEF position (GEO-like relay) per SPEC; unpin resumes via rephase_to at the current position.
2) preview_orbit{id,lat,lon}: compute the new orbit on a COPY (rephase_to) and return orbit_preview with the next 95 min ground track (30 s steps, split into segments at the antimeridian) — must run < 5 ms. Add rate limiting (max 20/s per client).
3) Optional TLE mode: `sgp4` dependency; backend/app/sim/tle.py parses a bundled `data/starlink_sample.tle` (include a tiny sample file — 60 sats — that I will refresh from CelesTrak before the event; if the file is missing, fall back to Walker). Provide a `constellation.mode: 'walker'|'tle'` config; in TLE mode propagate with sgp4 (TEME->ECEF via GMST rotation) vectorised with SatrecArray. Keep rephase/drag disabled in TLE mode (frontend shows "drag disabled for real TLE data").
4) Eclipse flag per sat: in_shadow(r_eci) using a cylindrical shadow with Sun direction fixed along +x_eci (SPEC §7); expose in frames as st=2.

TESTS: add/remove keeps frame ids stable; pinned sat does not move across 1000 s; preview_orbit track starts at the target and has 190 points; eclipse fraction for a 550 km LEO is between 25% and 40% over one orbit; TLE parse test with the sample file.

DONE WHEN: tests green; headless run still passes SPEC §16 acceptance.
```

---

## M2 — Topology v2 + plane/node failures (1.5 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior network engineer. Read docs/SPEC.md sections 6, 7.
NOTE (Person 1): any new command/field must be added to SPEC §12, schemas.py, types.ts and docs/CONTRACT_CHANGES.md in one commit, plus a sample message in docs/samples/.

TASK:
1) topology.py: add per-node `degree budget` (default 4; ground stations unlimited), support removed/failed nodes (excluded), and expose `ttl` computation helper `link_ttl(P_now, P_future_list, links)` returning seconds-until-invalid for each link using forward positions at +5…+60 s (vectorised; 12 forward steps). Cache the future positions once per tick.
2) conditions.py: fail_plane{plane} (all sats of a plane down for a duration or until restored), fail_region{lat,lon,radius_km} (all sats currently inside + their links down for N seconds — models a solar-storm/anti-satellite-debris event), restore_all. Emit rich events ("Plane 4 lost — 10 satellites offline").
3) Engine: `graph_partitioned` indicator (are all ground stations mutually reachable?) and `isolated_stations` list in the frame; emit crit event when a station becomes isolated.
4) Frontend types updated for new commands (no UI yet).

TESTS: fail_plane marks exactly S sats down and removes their links from the routing graph; fail_region selects the right sats given a lat/lon; ttl for a link that will break in 30 s is ~30 s (+/- 5 s); partition detection on a synthetic split.

DONE WHEN: tests green; headless: failing plane 3 at t=300 leaves Adaptive PDR > 85% (print) while Static drops lower.
```

---

## M3 — Condition model v2: storms, eclipse, flash crowd (1.5 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior simulation engineer. Read docs/SPEC.md sections 7, 8.

TASK:
1) Storm cells: Storm(id, lat, lon, radius_km, intensity 0..1, vel_lat/vel_lon deg/s optional drift). add_storm / move_storm / remove_storm commands. A GSL's p_weather = 0.15*intensity*falloff when its ground station is inside the radius (falloff = 1 - d/radius). Include p_weather in survive(); ISLs unaffected. Storm cells drift slowly if velocity set. Include storms in frames (position, radius, intensity).
2) Eclipse derate: ISL capacity x0.5 for links touching a satellite in shadow (st=2), as in SPEC §7; show effect in rho.
3) Demand model: flow demand = base_mbps * flow_scale * diurnal(t, src_lon) where diurnal is 0.7 + 0.3*cos(2*pi*(local_hour-20)/24) (local hour from the station's longitude and sim time t starting at 12:00 UTC); toggleable (config.traffic.diurnal=true). Commands: set_flow_scale, set_hotspot{gs_id,factor,duration_s} (multiplies all flows touching that station: "flash crowd").
4) Risk integration: loss_term uses p_weather+p_cong (SPEC §7), expiry_term from M2 ttl.

TESTS: storm over a ground station reduces survive on its GSLs only; eclipse halves capacity; diurnal bounds [0.4,1.0]; hotspot expires.

DONE WHEN: tests green; add a headless demo where a storm over Singapore at t=300 shows Static PDR dropping for SIN flows while Adaptive reroutes to other GSLs/other satellites (print per-flow PDR before/after).
```

---

## M4 — Routing v2: predictive, splitting, explainable (2 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior routing/algorithms engineer. Read docs/SPEC.md section 9 and 7 (risk).
NOTE (Person 1): any new command/field must be added to SPEC §12, schemas.py, types.ts and docs/CONTRACT_CHANGES.md in one commit, plus a sample message in docs/samples/.

TASK (modify routing/adaptive.py, cost.py, metrics.py):
1) Predictive risk: use link ttl (M2) so links about to leave range/LOS in < 60 s get expiry_term; add a "make-before-break" behaviour: for a flow whose primary path contains a link with ttl < 8 s, pre-compute the alternative and switch BEFORE the link dies (count as a "proactive reroute" separately from "reactive reroute"). Expose both counters.
2) Congestion splitting refinement: adaptive chunks = 4 by default; make it dynamic: if the primary path's max rho < 0.6 use 1 chunk (cheaper, fewer jumps), else 4; keep stickiness. Add `max_stretch` guard: reject a split path whose latency > 1.6x the best path latency.
3) Explainability: for each flow, produce `explain`: {chosen_cost, alt_cost, reason: 'failure'|'congestion'|'handover'|'prediction'|'init', detail:'Avoided S014-S022 (utilisation 94%)'}. Provide it in frames under flows[i].adaptive.explain and log as events when the reason is not 'init'.
4) Tunables via set_weights and set_params {chunks, stickiness, detect_delay_s}. Add a "weights preset" concept: latency-first (2,0.5,0.5), balanced (1,1,1), reliability-first (0.5,1,2).
5) Metrics: add proactiveReroutes, reactiveReroutes, avgStretch (adaptive path latency / static path latency).
6) Perf: profile; keep adaptive.update p95 < 60 ms for 8 flows, < 120 ms for 20 flows (document). If needed, implement a compact custom Dijkstra with heapq over adjacency lists using numpy-precomputed weights instead of NetworkX in the hot loop, keeping NetworkX for tests/validation; assert both produce equal-cost paths in a randomized test.

TESTS: proactive reroute happens before a link's ttl hits 0 in a constructed scenario (no blackhole time); explain reasons are correct; weights presets change paths as expected; randomized equivalence test between custom Dijkstra and NetworkX on 200 random graphs.

DONE WHEN: tests green; headless shows proactiveReroutes > 0 and Adaptive failure-recovery time lower than in P3; report numbers.
```

---

## M5 — Scenario engine (1.5 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior engineer. Read docs/SPEC.md sections 11, 12.

TASK: backend/app/sim/scenarios.py + REST.
- Scenario = {name, title, description, duration_s, seed, config_overrides, events:[{t, cmd, args}]}. The engine executes scheduled events at the right sim time (deterministic).
- Built-in scenarios (JSON files in backend/app/scenarios/*.json):
  1. calm_baseline — nothing special (shows steady state).
  2. solar_storm — failure intensity x10 for 5 min, 30% of satellites go eclipse-derated via fail_region + eclipse emphasis, one plane lost at t=180.
  3. flash_crowd — hotspot x4 on Delhi & London for 4 min.
  4. monsoon_storm — storm cells over Singapore (intensity 0.9) and Mumbai-region (use Delhi station if no Mumbai) drifting east.
  5. gateway_down — all GSLs of New York fail at t=120 for 3 minutes.
  6. cascade — random link failures every 10 s growing in rate, then a plane loss, then recovery.
- Commands: load_scenario{name}, stop_scenario. Frames include scenario {name, progress, nextEvent}.
- REST: GET /api/scenarios (list with titles/descriptions), POST /api/scenarios (upload custom JSON; validate), GET /api/scenarios/{name}.
- Scenario events are logged with a distinctive kind 'scenario'.

TESTS: scenario replay is deterministic (same seed => same summary); events fire at the right t; invalid scenario rejected with clear errors.

DONE WHEN: each built-in scenario runs headless for its duration and prints Adaptive vs Static summary; Adaptive wins in all six (if one does not, investigate the sim — don't tune to cheat).
```

---

## M6 — Benchmark runner (2 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior engineer / data scientist. Read docs/SPEC.md sections 10, 16, 17(6).
NOTE (Person 1): any new command/field must be added to SPEC §12, schemas.py, types.ts and docs/CONTRACT_CHANGES.md in one commit, plus a sample message in docs/samples/.

TASK: backend/app/sim/benchmark.py + REST + CLI.
- run_benchmark(scenario, seeds=[1..5], duration_s=1800, dt=2.0) running headless Engines (use multiprocessing Pool, one process per seed) and returning: per-algorithm time series (every 10 sim-s: latMs, pdr, thrMbps, cumulative reroutes), and summary stats mean ± std across seeds: avg latency, p95 latency, PDR, throughput, reroutes, mean recovery time, link uptime, blackhole seconds.
- Also run an "ablation" set: Static, Dijkstra-on-live-graph (distance weights, ignores congestion/risk, reroutes on failure) [implement `LiveDijkstraRouter` as a third algorithm], Adaptive. This matches slide 5's three-row table (Static Shortest Path / Dijkstra on Live Graph / Adaptive Cost-Aware). Add it as a third universe in the engine for benchmark mode only (config.benchmark_three_way).
- REST: POST /api/benchmark {scenario, seeds, duration_s} -> {job_id}; GET /api/benchmark/{id} -> {status, progress, result}. Jobs run in a background thread/process; progress reported. Cache results by (scenario,seeds,duration,config hash) in backend/.cache.
- Exports: GET /api/benchmark/{id}/csv and /json.
- CLI: `python -m app.sim.benchmark --scenario solar_storm --seeds 5 --out results/` writes results.json, summary.csv, and a markdown table docs/BENCHMARK.md with the exact numbers + the config used.
- A slide-ready helper: `python -m app.sim.benchmark_slide` prints the numbers in the same layout as slide 8 (Average latency, Packet delivery ratio, Failure recovery time, with improvement % rows) so the deck can be updated with TRUE numbers.

TESTS: result schema; mean/std correctness on a mock; three-way ordering sanity (Adaptive >= LiveDijkstra >= Static on PDR in the failure-heavy scenario); cache hit returns instantly.

DONE WHEN: running the benchmark for all 6 scenarios finishes in < 3 minutes total on a laptop; BENCHMARK.md exists; paste the summary table.
```

---

## M7 — Protocol hardening & performance (1.5 h)  ·  **🧑‍💻 PERSON 1 · Backend**

```text
ROLE: Senior backend engineer. Read docs/SPEC.md sections 11, 12.

TASK:
1) Compact frames: keep object frames for readability, but add `?fmt=compact` that sends arrays (sats as flat Float32 arrays inside JSON or msgpack — choose msgpack via `msgpack` + `@msgpack/msgpack` on the frontend if bandwidth > 60 KB/frame, else keep JSON). Measure before/after; keep whichever hits < 30 KB/frame for 120 sats + 20 flows.
2) Send ground stations/flows definitions only on change ('config_delta' messages); frames carry only dynamic data.
3) Backpressure: per-client send queue of size 1 (latest frame wins). Heartbeat ping/pong every 10 s; server closes dead sockets.
4) Multi-client: commands from any client apply to the shared sim; add a `client_count` field and `presenter` concept: first connected client may pass `?role=viewer` for read-only (commands rejected). Useful for projecting the screen while controlling from a phone.
5) Tick guard: if tickMs > 90 for 20 consecutive ticks, auto-reduce routing cadence to every 10 ticks and emit a warn event; restore when healthy.
6) Stress test script scripts/stress.py: 5 simultaneous clients for 60 s, 20 flows, 200 sats; report p95 tickMs and dropped frames.

DONE WHEN: stress test shows p95 tick < 80 ms with 200 sats / 20 flows and 5 clients; frame size numbers reported.
```

---

## M8 — Frontend design system & layout (2 h)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Principal frontend/UI engineer with strong visual design sense.
NOTE (Person 2): use scripts/mock_server.py until the relevant sync is delivered; never block on backend work. Read docs/SPEC.md sections 13, 14. Also load and follow the frontend-design skill if you have it.

TASK: Rebuild the shell of the app to look like a mission-control product, not a student demo.
1) Design system in src/styles + src/ui/: tokens (SPEC §14), components: Panel, Card, Stat, Badge, Button (primary/ghost/danger), IconButton, Tabs, Slider (custom, tabular value), Toggle, Select, Tooltip, Toast, Kbd, Divider, SegmentedControl. All keyboard accessible, focus rings in teal.
2) Layout: top bar (logo "SatRoute", tabs Network View · Controls · Performance · Logs, scenario selector, status pill "Simulation Running", sim clock, speed chip, connection dot) / main area: map (left) + right dock (Live Metrics, Flows, Inspector as collapsible sections) / bottom legend bar + "All Systems Nominal" status. Responsive down to 1280×720 (primary demo resolution) and 1920×1080.
3) Motion: framer-motion for panel transitions (150–200 ms), number tween on metrics, subtle pulse on the live pill. No heavy animation on the map container.
4) Dark theme only, but all colours via CSS variables.
5) Empty/loading/error states for every panel (skeleton shimmer while connecting).
6) Performance rule: panel re-renders must not depend on 60 fps map state; map state lives outside React state (refs) — verify with React Profiler that panels render ≤ 10 Hz.

DONE WHEN: screenshot comparison to the slide-7 dashboard shows equal or better polish; Lighthouse accessibility >= 90; profiler confirms panel render rate.
```

---

## M9 — Map v2: footprints, trails, day/night, particles (2 h)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Senior frontend engineer (deck.gl). Read docs/SPEC.md section 13.
NOTE (Person 2): use scripts/mock_server.py until the relevant sync is delivered; never block on backend work.

TASK (map/layers.ts, MapView.tsx):
1) Satellite icons: IconLayer with an SVG sprite atlas (small solar-panel satellite glyph, rotated to heading using vlat/vlon), colour by state: ok white/teal halo, down red, eclipse dim blue, pinned gold ring, manual (recently dragged) pulsing ring for 5 s.
2) Orbit trails: for the hovered/selected satellite draw its next ~95-minute ground track (request preview_orbit with its current position, split at the antimeridian) as a faint PathLayer; for all sats optionally show short past trails (last 40 s, ring buffer on the client) toggled in settings.
3) Coverage footprints: ScatterplotLayer (radiusUnits 'meters', stroked, alpha 0.06 fill) for ground stations (radius from SPEC §6.3 formula) and optional for all sats (toggle; default off).
4) Day/night terminator: compute subsolar point from sim time (declination fixed at 0 for simplicity or sinusoidal over the year start-date), draw a PolygonLayer shading the night side (rgba(0,0,0,0.35)) with soft edge; updates every second.
5) Packet particles: TripsLayer along each flow's adaptive primary path (and static path in compare view, orange) with trailLength ~ 1.5 s of animation time; speed proportional to path latency so long paths look slower; throttle to 10 fps updates for geometry, 60 fps for the time uniform.
6) Storm cells: translucent animated circles (PolygonLayer of circle polygons) with intensity-based colour; draggable (move_storm) using the same drag module.
7) Link rendering: width by capacity/utilisation, glow for active-path links; failed links blink for 1 s then settle to dashed red; handover animations: GSL line fades in over 0.5 s.
8) Settings popover to toggle each of the above layers.

PERF: keep >= 55 fps with 200 sats + 20 flows + particles (measure using the in-app FPS counter and report).

DONE WHEN: side-by-side with the prototype it looks dramatically richer yet smooth; fps report pasted.
```

---

## M10 — Interaction v2: drag with live orbit preview, add/pin/remove (2 h)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Senior frontend engineer (interaction design).
NOTE (Person 2): use scripts/mock_server.py until the relevant sync is delivered; never block on backend work. Read docs/SPEC.md section 13 and pitfalls 1–2.

TASK (map/drag.ts, panels/Inspector.tsx, store):
1) Drag a satellite: while dragging, throttle preview_orbit at 15 Hz and render (a) the satellite at the cursor, (b) the predicted NEW ground track as a bright dashed teal path, (c) a ghost of the OLD track in grey, (d) a tooltip "New orbit: inclination 53° → 58° · period 95.5 min" computed from the server response (extend orbit_preview with inc_deg, period_s). On drop send move_sat; the satellite gets a 5-s pulsing ring and a toast "Satellite S042 re-phased".
2) Impact preview while dragging (the wow moment): server `preview_impact{id,lat,lon}` runs a cheap what-if (rebuild topology with the moved sat, compute only Adaptive route cost for flows) and returns {latencyDeltaMs, affectedFlows:number}. Show "Predicted effect: −3.2 ms avg latency, 2 flows reroute". Rate-limit to 5 Hz; if the server is slow, skip.
3) Drag ground stations (with footprint following), storm cells (M9), and "pin" a satellite (right-click menu or Inspector button) which freezes it like a geostationary relay (gold ring).
4) Add satellite: toolbar button "+ Satellite" then click map (ghost follows the cursor, Esc cancels); "+ Ground station" with a name prompt; "Delete" removes selected (with Undo toast for 6 s: Undo = re-add with the same orbit via a server `undo_last` stack of the last 10 topology edits).
5) Context menu (right-click) on sat/link/GS/empty map with relevant actions (Fail, Restore, Pin, Remove, Add flow from here, Add storm here).
6) "Create flow" flow: select a source ground station, then a destination -> modal to set Mbps -> add_flow. Flow list supports delete and Mbps editing.
7) Touch support (pointer events only, no mouse-specific APIs); long-press for context menu.
8) Keyboard: Del removes selected, P pins, F fails, R restores, Space play/pause, 1/2/3 view (Adaptive/Static/Compare), ? shows a shortcuts overlay.

DONE WHEN: dragging feels instantaneous and educational (orbit preview + impact preview), map pan never conflicts, undo works. Record a 30 s capture.
```

---

## M11 — Controls, Performance, Logs tabs (2.5 h)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Senior frontend engineer + data-viz.
NOTE (Person 2): use scripts/mock_server.py until the relevant sync is delivered; never block on backend work. Read docs/SPEC.md sections 10, 12, 14 and PROTOTYPE P7 for the metrics panel.

TASK: Implement the three remaining tabs matching slide 7's tab names.
1) Controls tab (full panel over the right dock): groups — Simulation (play/pause/reset/speed with presets 1×,10×,60×,120×, seed input + "randomise"), Constellation (planes, sats per plane, altitude, inclination, phasing — "Apply & restart" via POST /api/config; show live count and period readout), Links (ISL max range, max degree, elevation mask, capacities), Failures (intensity, MTBF display, detection delay, manual "Break N random links", "Fail plane N", "Region failure here"), Routing (algorithm view, weights a/b/c with the formula rendered "Cost = a·Latency + b·Congestion + c·Failure Risk", presets latency-first/balanced/reliability-first, chunks, stickiness), Traffic (flows table with edit/add/delete, global demand ×, diurnal toggle, hotspot button), Scenarios (cards with title/description/duration, "Run" button, progress bar, "Stop"), Layers (map toggles from M9). Every control is debounced (200 ms) and optimistic with server confirmation.
2) Performance tab: live charts (Recharts) of last 5 minutes sim-time: latency (Adaptive vs Static lines), PDR, throughput, reroutes cumulative (+ proactive/reactive stacked), with a shared hover cursor; a "Benchmark" section: scenario dropdown, seeds, duration, "Run benchmark" button (POST /api/benchmark, progress bar), results rendered as the same three bar groups as slide 8 (Average latency / Packet delivery ratio / Failure recovery time) with three bars each (Static, Live Dijkstra, Adaptive), error bars (std), a summary table with improvement % and "Download CSV/JSON/PNG" (PNG via html-to-image).
3) Logs tab: virtualised table (react-window) of events with columns time, level icon, kind, message; filters (level, kind, text), auto-scroll toggle, click a row to focus the satellite/link on the map (fly-to), "Export .log". Keep 5000 entries in a ring buffer.
4) Persist UI settings (layers, view, tab) in localStorage (UI settings only).

DONE WHEN: all tabs work against the live backend; benchmark run from the UI produces charts that exactly match `python -m app.sim.benchmark` output for the same seeds/scenario (assert by eye and with a small script comparing JSON).
```

---

## M12 — 3D globe mode (2 h; skip if behind schedule)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Senior frontend engineer (deck.gl / WebGL).
NOTE (Person 2): use scripts/mock_server.py until the relevant sync is delivered; never block on backend work. Read docs/SPEC.md section 13.

TASK:
1) Add a "2D Map | 3D Globe" toggle. 3D uses deck.gl `_GlobeView` with the same data. Satellites sit at altitude: position = [lon, lat, alt_km*1000*exaggeration] with exaggeration 8x so they hover visibly above the surface (slider 1–15x). Links as `ArcLayer`/`LineLayer` with 3D endpoints (great-circle curvature via ArcLayer height ratio 0.05–0.15 for ISLs, straight for GSLs). Land GeoJSON on the globe; atmosphere glow ring (a slightly larger translucent sphere via SimpleMeshLayer or a CSS radial gradient behind the canvas).
2) Camera: auto-rotate toggle, "Follow satellite" (centre the selected sat each frame), "Follow flow" (orbit around the route), smooth transitions using `FlyToInterpolator`.
3) Interaction in 3D: hover/click picking works; satellite dragging in 3D uses `viewport.unproject` onto the globe surface (drag by lon/lat, same server commands). If unproject returns null (cursor off the globe) ignore the move. If drag proves unreliable on the globe within 45 minutes of effort, fall back to: dragging disabled in 3D with a hint "Switch to 2D to drag" — do not sink more time.
4) Performance: keep >= 45 fps on a mid laptop with 120 sats; reduce link width/particles automatically if fps < 40 (adaptive quality).
5) Cinematic preset: "Showcase" button = slow auto-rotate + hide panels except a floating compact metrics bar.

DONE WHEN: toggling between 2D and 3D keeps selection and view-mode state; 3D looks great in a screenshot; fps numbers reported.
```

---

## M13 — Story mode + compare split-screen (2 h)  ·  **🎨 PERSON 2 · Frontend**

```text
ROLE: Senior full-stack engineer with product sense.
NOTE (Person 2): use scripts/mock_server.py until the relevant sync is delivered; never block on backend work. Read docs/SPEC.md section 1.

TASK:
1) Compare split view: a 'Split' mode showing two synchronised maps side by side — left "Static Shortest Path", right "Adaptive Cost-Aware" — same sats/failures, each map showing only its own routes/loads (link colours from that algorithm's rho), with a centre divider, and a live "scoreboard" strip across the top (latency / PDR / throughput / reroutes with deltas). One shared interpolation loop, two Deck instances (or two views in one Deck using `views` + `layerFilter`; prefer the latter for performance). Camera synced.
2) Story mode ("▶ Guided Demo" replaces the P8 auto-demo): a director module (src/story/director.ts) executing a scripted timeline of steps; each step has {at, caption, voiceover?, actions[]} where actions call store/socket commands, camera moves, view changes, selections, and highlight rings. The script (≈ 2.5 minutes): intro on the globe/map (Showcase) -> explain LEO dynamics (zoom on one sat's footprint) -> start `calm_baseline` and select DEL→LON -> compare view -> fail an active link -> flash crowd scenario -> drag a satellite programmatically with the orbit preview visible -> monsoon storm over Singapore -> open the Performance tab and show the benchmark numbers (use cached benchmark) -> closing caption with "Adaptive: −X% latency, +Y pts delivery, Z× faster recovery" computed from the cached benchmark (never hard-coded).
3) Presenter tools: caption bar styling (large, high-contrast), pause/resume/skip-step, progress dots, `Esc` exits and restores the previous UI state. A "Presenter notes" side popup (toggle) shows the talking points for the current step (from the script) for the human presenter.
4) A fallback: if the backend is unreachable at start of story mode, automatically switch to replay mode (record a replay for each scenario via the P8 record script — extend it to record scenarios).

DONE WHEN: the guided demo runs unattended end to end 3 times; split view stays in sync; numbers in the closing caption equal the cached benchmark values.
```

---

## M14 — QA, packaging, pitch kit (3 h; ALWAYS do this)  ·  **👥 BOTH**

```text
ROLE: Staff engineer / release manager / technical writer.

TASK:
1) QA sweep: write docs/QA_CHECKLIST.md and execute it — cold start, reconnect, 10-minute soak (memory growth < 50 MB, no fps decay), every command, every scenario, drag/add/remove/undo, all tabs, both view modes, 1280×720 and 1920×1080, Chrome + one other browser. Fix all P0/P1 bugs. Add Playwright smoke tests (3 tests: loads and shows >100 sats; failing a link changes Adaptive path; benchmark button yields chart).
2) Packaging: Dockerfile (multi-stage: build frontend -> serve static via FastAPI StaticFiles) + docker-compose.yml; `docker compose up` serves everything at :8000. Also a no-Docker `scripts/run_prod.sh`. Pre-bundle all assets (no CDN calls; verify by running with the network disabled).
3) Docs: README (what/why, architecture diagram, 3-command quickstart, feature list with GIFs placeholders, algorithm explanation with the cost formula, limitations honestly stated: circular orbits/no J2, fluid-flow model, simplified weather/eclipse, simulated not measured, and how real data (TLE, real traffic) plugs in), docs/ALGORITHM.md (static vs live-Dijkstra vs adaptive with pseudocode and complexity), docs/BENCHMARK.md (from M6).
4) Pitch kit in docs/PITCH/: (a) 3-minute pitch script with timings and exact clicks (maps to the 5 judging moments in SPEC §1); (b) 12 judge Q&A with crisp answers (why not just Dijkstra? how do you detect failures? how realistic is the orbit model? how does it scale to 5,000 sats? what about inter-satellite link pointing/acquisition time? how would you deploy it? what is novel vs existing simulators like STK/ns-3/Hypatia? what about security? how do you avoid route flapping? what did you learn?); (c) a slide-update list mapping each deck slide to the real screenshot/number that should replace it (esp. slide 8 -> real benchmark values, slide 7 -> a real screenshot), and a one-page architecture graphic spec.
5) Final rehearsal: run the full pitch twice from a clean machine boot using only the README; time it; note risks in docs/DEMO_RISKS.md with mitigations (replay mode, offline assets, backup video recording).
6) Tag release v1.0 and produce a 60-second screen recording script.

DONE WHEN: QA checklist all green, Docker run works offline, pitch rehearsed twice within 3:00, backup recording exists.
```

---

## MVP Definition of Done (checklist)

- [ ] Every feature in the deck exists and works live (orbit sim, topology, conditions, routing, dashboard)
- [ ] Drag/add/pin satellites with orbit + impact preview
- [ ] Six scenarios + storms + eclipse + flash crowds
- [ ] Predictive, congestion-aware adaptive routing with "why this path" explanations
- [ ] Benchmark charts from real runs (and slide 8 updated with them)
- [ ] 2D map + 3D globe + split compare + story mode
- [ ] Docker one-command run, offline-safe, replay fallback
- [ ] Pitch script, Q&A, and risk list rehearsed

## Who signs off what
- **Person 1:** headless numbers per scenario (M5), `docs/BENCHMARK.md` (M6), stress test (M7), tests green.
- **Person 2:** fps report (M9), drag/impact-preview capture (M10), tabs matching backend output (M11), unattended story-mode runs (M13).
- **Both:** sync integration checks, M14 QA + two pitch rehearsals.
