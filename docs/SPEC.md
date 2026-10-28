# SPEC.md — Technical Contract for "SatRoute" (Intelligent Routing for Dynamic Satellite Networks)

> Every agent session: read this file first, then do ONLY the current phase from PROTOTYPE_PLAN.md or MVP_PLAN.md.
> If this spec and a phase prompt disagree, the phase prompt wins for that phase; otherwise the spec is the source of truth.
> When something is unspecified, pick the default written here. Do not stop to ask.

---

## 0. Agent Rules (paste at the top of every agent session)

1. Read `docs/SPEC.md` and the referenced sections before writing code.
2. Work only on the current phase. Do not refactor unrelated files. Do not add features not in the phase.
3. Write tests alongside code. Run them. Paste real output in your final message.
4. Python: 3.11, type hints everywhere, pure functions in `sim/`, no hidden global state except the single `Engine` instance in `main.py`.
5. TypeScript: strict mode, no `any`, types for WS messages live in `frontend/src/net/types.ts` and must mirror `backend/app/schemas.py`.
6. Never invent metrics. Every number shown in UI comes from the simulation.
7. End each phase with: (a) files changed, (b) how to run, (c) what was verified, (d) known gaps. Then `git commit -m "<phase id>: <summary>"`.
8. If a library API is uncertain, check the installed version's docs/source in `node_modules` or `site-packages` rather than guessing.

---

## 1. Product Definition

**One sentence:** A live, interactive LEO constellation simulator where you can watch data routed across moving satellites, break things (links, satellites, whole regions, weather), drag satellites around, and watch an **Adaptive cost-aware router** beat a **Static shortest-path baseline** with real, measured numbers.

**Judging-critical moments (design everything to make these shine):**
1. Satellites visibly orbiting; links appearing/disappearing as they move.
2. Click a link on the active path → Static flow turns red (blackholed), Adaptive reroutes in ~1–2 s with a visible path change.
3. Drag a satellite to a new spot → its orbit re-phases, topology rebuilds live, routes adapt.
4. Flash-crowd congestion → Adaptive splits traffic across paths; Static melts.
5. Performance tab → benchmark charts from real simulation runs (replace the numbers on slide 8 with these).

---

## 2. Final Tech Stack (do not re-debate)

**Backend:** Python 3.11, FastAPI, uvicorn[standard], WebSocket for live frames, REST for config/benchmarks, NumPy (vectorised orbit + link math), NetworkX (graph + Dijkstra), SciPy (optional), Pydantic v2, orjson, pytest. MVP adds `sgp4` (TLE import).

**Frontend:** Vite + React 18 + TypeScript (strict) + Tailwind CSS + Zustand (state) + deck.gl 8.9.x (`@deck.gl/core`, `layers`, `geo-layers`, `extensions`, `react`) for the 2D map (WebGL, smooth with 100+ moving objects) + `world-atlas` + `topojson-client` (bundled country shapes → NO map-tile / internet dependency) + Recharts (charts) + lucide-react (icons). MVP adds deck.gl `_GlobeView` for the 3D mode.

**Why not Leaflet/Cesium:** Leaflet markers are DOM-heavy and janky at 60 fps; Cesium is heavy and hard to make draggable. deck.gl + own picking gives smooth rendering and reliable drag.

**Architecture:** Server-authoritative simulation. Backend runs the sim loop at 10 Hz wall-clock and streams "frames". Frontend interpolates at 60 fps. Frontend only sends commands.

```
 ┌──────── Backend (Python) ─────────────────────────────────────────────┐
 │ Orbit Engine → Topology Builder → Condition Model → Routing Engines    │
 │   (NumPy)        (LOS, range,       (latency, loss,    (Static,        │
 │                   elevation)         failures, load)    Adaptive)      │
 │                                     ↓                                  │
 │              Metrics  →  Engine loop (10 Hz)  →  WebSocket /ws         │
 └────────────────────────────────────────────────────────────────────────┘
                                     ↕ JSON frames / commands
 ┌──────── Frontend (React + deck.gl) ───────────────────────────────────┐
 │ Zustand store → interpolation (60fps) → Map layers + Dashboard panels  │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Repo Layout

```
satroute/
  docs/            SPEC.md  PROTOTYPE_PLAN.md  MVP_PLAN.md
  scripts/         dev.sh  (starts backend + frontend)
  backend/
    requirements.txt
    app/
      main.py            FastAPI app, /ws, REST
      config.py          defaults (dataclass / pydantic)
      schemas.py         pydantic models for WS messages
      sim/
        constants.py
        orbit.py         Walker constellation, propagate, rephase
        topology.py      ISL + ground link builder (LOS, range, elevation, hysteresis)
        conditions.py    link/node state, failures, queueing, loss
        traffic.py       flows + fluid-flow evaluator
        routing/
          cost.py        link cost function
          static.py      static baseline
          adaptive.py    adaptive router
        metrics.py
        engine.py        the tick loop (pure, headless-capable)
        scenarios.py     (MVP)
        benchmark.py     (MVP)
    tests/
  frontend/
    src/
      main.tsx  App.tsx
      net/   types.ts  socket.ts
      store/ useSim.ts
      map/   MapView.tsx  layers.ts  interpolate.ts  drag.ts
      panels/ TopBar.tsx  LiveMetrics.tsx  Controls.tsx  Performance.tsx  Logs.tsx  Inspector.tsx
      lib/   geo.ts  format.ts
      styles/ index.css
```

---

## 4. Constants & Units

Distances km, time s, rates Mbps, angles radians internally (degrees at API boundary), latency ms.

```python
# sim/constants.py
R_E       = 6371.0            # km
MU        = 398600.4418       # km^3/s^2
C_KMS     = 299792.458        # km/s
OMEGA_E   = 7.2921159e-5      # rad/s  Earth rotation
ATMOS_KM  = 80.0              # LOS grazing margin above surface
PROC_MS   = 0.3               # per-hop processing delay
```

Sanity numbers at 550 km: a = 6921 km, period ≈ 5730 s, speed ≈ 7.59 km/s.

---

## 5. Orbit Model (circular two-body, no J2)

Each satellite: inclination `inc`, RAAN `Ω`, argument of latitude at t=0 `u0`, radius `a`. Mean motion `n = sqrt(MU/a^3)`. `u(t) = u0 + n·t`.

```python
# sim/orbit.py
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field
from .constants import R_E, MU, OMEGA_E

@dataclass
class Constellation:
    plane: np.ndarray   # (N,) int
    inc:   np.ndarray   # (N,) rad
    raan:  np.ndarray   # (N,) rad
    u0:    np.ndarray   # (N,) rad
    a:     np.ndarray   # (N,) km
    pinned: np.ndarray = field(default=None)       # (N,) bool; pinned sats hold pin_ecef
    pin_ecef: np.ndarray = field(default=None)     # (N,3)

    def __post_init__(self):
        n = len(self.a)
        if self.pinned is None:   self.pinned = np.zeros(n, bool)
        if self.pin_ecef is None: self.pin_ecef = np.zeros((n, 3))

    @property
    def n(self) -> np.ndarray:
        return np.sqrt(MU / self.a**3)

def walker_delta(T: int, P: int, F: int, inc_deg: float, alt_km: float) -> Constellation:
    """T total sats, P planes, phasing F. Default demo: T=120, P=12, F=1, inc=53, alt=550."""
    S = T // P
    plane, raan, u0 = [], [], []
    for p in range(P):
        for s in range(S):
            plane.append(p)
            raan.append(2*np.pi*p/P)
            u0.append((2*np.pi*s/S + 2*np.pi*F*p/T) % (2*np.pi))
    N = P*S
    return Constellation(np.array(plane), np.full(N, np.radians(inc_deg)),
                         np.array(raan), np.array(u0), np.full(N, R_E + alt_km))

def propagate_eci(c: Constellation, t: float) -> np.ndarray:
    u = c.u0 + c.n * t
    cO, sO, ci, si = np.cos(c.raan), np.sin(c.raan), np.cos(c.inc), np.sin(c.inc)
    cu, su = np.cos(u), np.sin(u)
    x = c.a * (cO*cu - sO*ci*su)
    y = c.a * (sO*cu + cO*ci*su)
    z = c.a * (si*su)
    return np.stack([x, y, z], axis=1)

def eci_to_ecef(r: np.ndarray, t: float) -> np.ndarray:
    th = OMEGA_E * t
    ct, st = np.cos(th), np.sin(th)
    return np.stack([r[:,0]*ct + r[:,1]*st, -r[:,0]*st + r[:,1]*ct, r[:,2]], axis=1)

def positions_ecef(c: Constellation, t: float) -> np.ndarray:
    P = eci_to_ecef(propagate_eci(c, t), t)
    if c.pinned.any(): P[c.pinned] = c.pin_ecef[c.pinned]
    return P

def ecef_to_latlon(r: np.ndarray):
    rn = np.linalg.norm(r, axis=1)
    return np.degrees(np.arcsin(r[:,2]/rn)), np.degrees(np.arctan2(r[:,1], r[:,0])), rn - R_E

def latlon_to_ecef(lat_deg, lon_deg, alt_km=0.0) -> np.ndarray:
    la, lo = np.radians(lat_deg), np.radians(lon_deg)
    r = R_E + np.asarray(alt_km)
    return np.stack([r*np.cos(la)*np.cos(lo), r*np.cos(la)*np.sin(lo), r*np.sin(la)], axis=-1)

def rephase_to(c: Constellation, i: int, lat_deg: float, lon_deg: float, t: float) -> None:
    """DRAG-TO-MOVE. Re-fit satellite i's orbit so that at time t it is exactly over (lat, lon),
    keeping its direction of travel (ascending/descending). If |lat| > inclination, the inclination
    is raised to |lat| (the point becomes the orbit's turning point). Orbit keeps propagating after."""
    phi, lam = np.radians(lat_deg), np.radians(lon_deg)
    lam_i = lam + OMEGA_E * t                      # ECI longitude of target
    inc = c.inc[i]
    if abs(phi) > inc: inc = abs(phi)
    s = np.clip(np.sin(phi) / np.sin(inc), -1.0, 1.0)
    u1 = np.arcsin(s); u2 = np.pi - u1             # u1 ascending (cos>=0), u2 descending
    ascending = np.cos(c.u0[i] + c.n[i]*t) >= 0
    u = u1 if ascending else u2
    raan = lam_i - np.arctan2(np.cos(inc)*np.sin(u), np.cos(u))
    c.inc[i] = inc
    c.raan[i] = raan % (2*np.pi)
    c.u0[i] = (u - c.n[i]*t) % (2*np.pi)
    c.pinned[i] = False

def ground_track(c: Constellation, i: int, t: float, horizon_s: float = 5700, step_s: float = 30):
    """Returns [[lon,lat],...] for the preview line shown while dragging (use a 1-sat sub-constellation)."""
    ts = np.arange(t, t + horizon_s, step_s)
    one = Constellation(c.plane[[i]], c.inc[[i]], c.raan[[i]], c.u0[[i]], c.a[[i]])
    out = []
    for tt in ts:
        lat, lon, _ = ecef_to_latlon(positions_ecef(one, tt))
        out.append([float(lon[0]), float(lat[0])])
    return out
```

Ground stations are fixed in ECEF (`latlon_to_ecef`). All link math is done in ECEF.

**Default constellation:** Walker-delta `120/12/1`, inc 53°, alt 550 km (12 planes × 10 sats). Reason: in-plane spacing ≈ 4350 km and adjacent-plane spacing ≈ 3600 km at the equator, both inside the ≈5000 km LOS limit, so the mesh stays connected. (A 6×8 constellation would NOT be connected — don't use it.)

---

## 6. Topology Builder

### 6.1 Line of sight between satellites
Closest approach of segment p1→p2 to Earth's centre must exceed `R_E + ATMOS_KM`.

```python
def los_clear(P1, P2, r_min):
    d = P2 - P1
    tt = np.clip(-np.einsum('ij,ij->i', P1, d) / np.einsum('ij,ij->i', d, d), 0, 1)
    closest = P1 + tt[:, None]*d
    return np.linalg.norm(closest, axis=1) > r_min
```

### 6.2 Inter-satellite links (ISL) — greedy + hysteresis
Parameters: `isl_max_range=5000 km`, `isl_build_frac=0.92`, `max_deg=4`.
1. All pairs (i<j) with `d ≤ isl_max_range` and LOS clear are *valid*.
2. **Keep** previously existing valid links first (sorted by distance) while degree < max_deg. (Hysteresis: a link survives until it is truly invalid → no flapping.)
3. **Add** new valid links with `d ≤ isl_max_range*isl_build_frac`, sorted by distance, while both endpoints have degree < max_deg.
Works for dragged/added satellites because it never assumes grid indices.

### 6.3 Ground–satellite links (GSL)
```python
def elevation_deg(G, S):                    # G:(g,3) ground ECEF, S:(n,3) sat ECEF
    V = S[None,:,:] - G[:,None,:]
    zen = G / np.linalg.norm(G, axis=1, keepdims=True)
    sin_el = np.einsum('gnk,gk->gn', V, zen) / np.linalg.norm(V, axis=2)
    return np.degrees(np.arcsin(np.clip(sin_el, -1, 1)))
```
Each ground station links to its top `K=3` visible satellites (`el ≥ el_min=25°`; an existing link survives until `el < el_min-2°`). Footprint (coverage) angular radius: `psi = arccos(R_E*cos(el)/(R_E+h)) - el` (≈ 8.3° ≈ 930 km at 550 km/25°).

### 6.4 Output
`Topology { isl: list[(i,j)], gsl: list[(g_node, s_node)], pos: (N,3) }`. Node numbering: satellites `0..N-1`, ground stations `N..N+G-1`.

---

## 7. Network Condition Model

Each link (ISL or GSL) has a stable id `"{min}-{max}"` and persistent state keyed by that id (so a failed link that drops out of range and returns is still failed until its timer expires).

| Quantity | Formula |
|---|---|
| propagation | `prop_ms = dist_km / C_KMS * 1000` |
| capacity | ISL `2000 Mbps`, GSL `1000 Mbps` (demo scale, configurable) |
| utilisation | `rho = load_mbps / capacity` (load per algorithm, see §8) |
| queueing | `queue_ms = min(Q0 * rho/(1-min(rho,0.97)), 200)`, `Q0 = 1.0` |
| base loss | `0.001` |
| congestion loss | `p_cong = 0.02*clip((rho-0.85)/0.15, 0, 1)**2` |
| overload | if `rho>1` everything is scaled by `1/rho` |
| per-link survive prob | `(1-p_base)*(1-p_cong)*(1-p_weather)*min(1,1/rho)` |
| per-link latency | `prop_ms + PROC_MS + queue_ms` |

**Random failures:** each tick, each up link fails with prob `1-exp(-dt/MTBF_link)`, `MTBF_link = 60000 s` (≈ one failure every ~200 sim-s across ~300 links; UI "failure intensity" multiplies the rate). Down duration `U(20, 90)` sim-s. Manual failures: `fail_link`, `fail_sat` (all links of that node down) until restored.

**Link risk (0..1)** used by Adaptive cost:
`risk = max(loss_term, recent_fail_term, expiry_term)` where
- `loss_term = clip((p_weather + p_cong) * 10, 0, 1)`
- `recent_fail_term = 0.6 * 0.5**((t - last_fail_t)/60)` (decays, half-life 60 s)
- `expiry_term = clip(1 - ttl/60, 0, 1)**2`, `ttl` = seconds until the link would leave range/LOS (forward-propagate positions at +5…+60 s in 5-s steps, vectorised). (Prototype: use `expiry_term = 0`; MVP implements it.)

**MVP extras:** storm cells (lat, lon, radius km, intensity) add `p_weather = 0.15*intensity` to GSLs of stations inside; eclipse (satellite in Earth's cylinder shadow, Sun fixed in ECI along +x) derates that satellite's ISL capacity ×0.5.

---

## 8. Traffic & Flow Evaluation (fluid model — fast and smooth)

`Flow {id, src_gs, dst_gs, mbps}`. Default 8 flows (Mbps): DEL→LON 600, NYC→SIN 500, LAX→TYO 400, SAO→JNB 300, DXB→SYD 350, LON→NYC 700, SIN→SYD 450, DEL→TYO 400.

Default ground stations (lat, lon): Delhi (28.61, 77.21), London (51.51, -0.13), New York (40.71, -74.01), Los Angeles (34.05, -118.24), São Paulo (-23.55, -46.63), Johannesburg (-26.20, 28.05), Dubai (25.20, 55.27), Singapore (1.35, 103.82), Tokyo (35.68, 139.69), Sydney (-33.87, 151.21).

**Each algorithm is evaluated in its own "parallel universe":** same physical network (same positions, failures, weather) but separate load accounting, so Static and Adaptive don't congest each other and the comparison is fair.

Evaluation per algorithm each tick:
1. A flow has 1..k *chunks* `(path, mbps)`.
2. `load[link] += chunk.mbps` for each link on each chunk path.
3. Compute `rho`, `queue_ms`, `survive` for every loaded link.
4. For each chunk: if any link on its path is **down** (or absent) → chunk is blackholed (delivered 0, counts as outage). Else `delivered = mbps * Π survive`, `latency = Σ link latency`.
5. Flow latency = delivered-weighted mean of chunk latencies. Flow PDR = Σdelivered / flow.mbps.

---

## 9. Routing

### 9.1 Cost function (the formula on slide 5)
```python
# sim/routing/cost.py
def link_cost(lat_ms, rho, risk, w):            # w = (a, b, c) default (1.0, 1.0, 1.0)
    rho = min(rho, 0.99)
    return w[0]*(lat_ms/10.0) + w[1]*(0.25*rho/(1.0-rho)) + w[2]*(4.0*risk)
```
Typical hop ≈ 1.2 (latency), congestion term 0.25 @50%, 1.0 @80%, 2.25 @90%, risk adds up to 4.

### 9.2 Static Shortest Path (baseline)
- Weight = distance only. Graph = all links that **exist physically** (in range/LOS/elevation), **ignoring failures and congestion** (it does not know about them).
- Path computed at flow start and then **held**. Recomputed only if a hop of the path physically ceased to exist (handover / out of range). Never recomputed because of failure or congestion.
- If a hop is failed → chunk is blackholed until the link is restored or the path physically changes.

### 9.3 Adaptive Cost-Aware Router
- Graph = only **up** links. Edge weight attribute `w` = `link_cost(...)` using that algorithm's own current load.
- **Detection delay:** a failure is only visible to Adaptive after `detect_delay_s = 1.0` sim-s (heartbeat timeout). Until then the chunk is blackholed (this is what makes recovery time realistic, ~1–3 s).
- **Incremental load assignment (gives congestion-aware splitting for free):**

```python
# sim/routing/adaptive.py  (core idea)
def route_all(G, flows, prev_paths, w, chunks=4):
    load = defaultdict(float)
    out = {}
    for f in sorted(flows, key=lambda f: -f.mbps):
        q = f.mbps / chunks
        paths = []
        prev_edges = edges_of(prev_paths.get(f.id, []))
        for _ in range(chunks):
            path = nx.dijkstra_path(G, f.src, f.dst, weight='w')   # 'w' precomputed once per cycle
            for e in edges_of([path]):
                load[e] += q
                refresh_weight(G, e, load[e], w)          # recompute 'w' only for touched edges
            paths.append((path, q))
        out[f.id] = merge_identical(paths)                # identical paths merged into one chunk
    return out
```
- **Stickiness (anti-flap hysteresis):** edges that were on the flow's previous paths get `w *= 0.9` when routing it.
- **Cadence:** re-route every 5 ticks (0.5 s wall) AND immediately when a failure is detected / topology edge set changes. Measure routing time; keep a full tick under 80 ms (precompute `w` for all edges once per cycle, then update incrementally).
- `reroute` event = primary (largest chunk) path node-sequence changed.

---

## 10. Metrics (per algorithm, plus network-level)

| Metric | Definition |
|---|---|
| End-to-end latency (ms) | delivered-traffic-weighted mean over flows, EWMA(0.2) for display |
| Packet delivery ratio (%) | Σdelivered / Σoffered |
| Throughput (Mbps/Gbps) | Σdelivered |
| Reroutes performed | cumulative count + per-minute rate (sim time) |
| Failure recovery time (s) | mean duration of outage episodes (flow delivered==0 → >0) that have ended |
| Link uptime (%) | `1 - failed_link_seconds / existing_link_seconds` (network-level) |
| Active failures | count of links/nodes currently down |

Keep a rolling 120-point history per metric (for sparklines). Benchmarks use cumulative values.

---

## 11. Engine Tick (headless-capable, deterministic with seed)

```
wall tick = 0.1 s;  sim_dt = 0.1 * time_scale   (default scale 20 → 2 sim-s per tick; range 1–120)
per tick:
  t += sim_dt (if running)
  P = positions_ecef(constellation, t)
  topo = build_topology(P, ground, prev_topo, params)
  conditions.step(topo, t, sim_dt, rng)          # failures, recoveries, weather, eclipse, expiry-risk
  routes_static   = static.update(...)
  routes_adaptive = adaptive.update(...)  (cadence rules)
  eval_static, eval_adaptive = evaluate(...)     # §8
  metrics.update(...)
  frame = build_frame(...)                       # §12
```
Engine exposes `step(dt_wall)`, `apply_command(cmd)`, `snapshot()`, and `run_headless(duration_s, seed)` for benchmarks/tests. Seeded `numpy.random.Generator`.

---

## 12. WebSocket Protocol (`/ws`, JSON)

**Server → client**
```ts
type Init = { type:'init'; config: SimConfig; ground: {id:number; name:string; lat:number; lon:number}[]; flows: Flow[]; nSats:number; planes:number[] }
type Frame = {
  type:'frame'; t:number; scale:number; running:boolean; tickMs:number;
  sats: {id:number; lat:number; lon:number; alt:number; vlat:number; vlon:number; st:0|1|2|3}[]; // st: 0 ok, 1 down, 2 eclipse, 3 manual/pinned. v* = deg per WALL second (for client extrapolation)
  links: {a:number; b:number; k:0|1; up:0|1; rho:number; ms:number; loss:number}[];                  // k: 0 ISL, 1 GSL; rho from the viewed algorithm
  flows: {id:string; adaptive:FlowEval; static:FlowEval}[];
  metrics: {adaptive:Metrics; static:Metrics; linkUptime:number; activeFailures:number};
  events: SimEvent[];       // only events since last frame
}
type FlowEval = { paths:{nodes:number[]; mbps:number}[]; ms:number; pdr:number; blackholed:boolean }
type Metrics  = { latMs:number; pdr:number; thrMbps:number; reroutes:number; rerouteRate:number; recoverS:number }
type SimEvent = { t:number; level:'info'|'warn'|'crit'; kind:string; msg:string }
type Ack = { type:'ack'; id?:string } | { type:'error'; msg:string } | { type:'orbit_preview'; id:number; track:[number,number][] }
```
**Client → server:** `{type:'cmd', cmd:string, args:object, id?:string}`
Commands: `play`, `pause`, `reset`, `set_scale{scale}`, `set_weights{a,b,c}`, `set_params{...}`, `fail_link{a,b}`, `restore_link{a,b}`, `fail_sat{id}`, `restore_sat{id}`, `move_sat{id,lat,lon}`, `move_gs{id,lat,lon}`, `preview_orbit{id,lat,lon}`, `set_flow_scale{factor}`, `add_flow{src,dst,mbps}`, `remove_flow{id}` — MVP adds `add_sat`, `remove_sat`, `pin_sat`, `add_gs`, `add_storm`, `move_storm`, `fail_plane{plane}`, `load_scenario{name}`.

Frame size target: < 40 KB for 120 sats + ~250 links. Send static data (ground stations, names) only in `init`.

---

## 13. Frontend Architecture

- **Store (Zustand):** `latestFrame`, `prevFrame`, `recvAt`, `ground`, `flows`, `ui` (selection, view mode `adaptive|static|compare`, tab, dragging), `history` (metric sparkline buffers), actions that call `socket.send(cmd)`.
- **Interpolation (`interpolate.ts`):** render loop with `requestAnimationFrame`; for each sat `lat = f.lat + f.vlat*(now-recvAt)/1000`, `lon` likewise with wrap to [-180,180]; clamp extrapolation to 300 ms. Layers re-created each rAF with `updateTriggers` set so deck.gl only re-uploads changed attributes.
- **Layers (order bottom→top):** graticule/ocean (background) → land `GeoJsonLayer` (countries from `world-atlas/countries-110m.json` via topojson-client) → coverage footprints (MVP) → ISL `LineLayer` (colour by rho: teal→amber→red; down = dim red dashed) → GSL `LineLayer` → static path `PathLayer` (orange, dashed via `PathStyleExtension`) → adaptive path `PathLayer` (teal, solid, wide) → ground stations (`IconLayer`/`ScatterplotLayer`, with labels via `TextLayer`) → satellites (`IconLayer`, picking enabled).
- **Antimeridian:** lines crossing ±180° must not streak across the map. Use `wrapLongitude: true` where the layer supports it, otherwise split the segment at the antimeridian in `lib/geo.ts`.
- **Dragging (robust method):** keep a ref to the `Deck` instance. On pointer-down over a satellite (`deck.pickObject({x,y,radius:8})` returns a sat) → call `deck.setProps({controller:{dragPan:false, dragRotate:false}})` synchronously, set `ui.dragging = id`. On pointer-move → `viewport.unproject([x,y])` → `[lon,lat]`, draw the dragged sat at the cursor locally, throttle `preview_orbit` to ~15 Hz (MVP). On pointer-up → send `move_sat{id,lat,lon}`, re-enable the controller. Wrap lon to [-180,180], clamp lat to ±85. Distinguish click vs drag with a 4-px threshold.
- **Selection inspector:** click sat/link/ground station → side card with live stats + action buttons (Fail link, Restore, Pin, Remove).
- **Packet particles (MVP):** `TripsLayer` along the adaptive primary path of the selected/all flows.

---

## 14. Design Tokens (match the deck)

```
--bg:#0A1428  --panel:#0F1E3A  --panel2:#13264A  --border:#1E3558  --text:#E6EEF8  --muted:#8FA3BF
--navy:#14264B  --teal:#3A93A8  --teal-bright:#4FC3D9  --orange:#E8843A
--ok:#3DD68C  --warn:#F5B942  --crit:#E5484D
Font: Inter (400/600/700); numbers tabular-nums. Panels: radius 12px, 1px border, subtle inner glow.
Colours: adaptive path = teal-bright, static path = orange dashed, down link = crit dashed, satellite = white w/ teal halo, ground station = orange.
```
Layout mirrors slide 7: top bar (tabs: Network View · Controls · Performance · Logs · status pill "Simulation Running"), map on the left (~70%), "Live Metrics" panel on the right with sparklines, legend + "All Systems Nominal" footer bar.

---

## 15. Config Defaults

```python
CONFIG = dict(
  constellation=dict(T=120, P=12, F=1, inc_deg=53.0, alt_km=550.0),
  isl=dict(max_range_km=5000.0, build_frac=0.92, max_deg=4),
  gsl=dict(el_min_deg=25.0, k=3, drop_margin_deg=2.0),
  capacity=dict(isl_mbps=2000.0, gsl_mbps=1000.0),
  failures=dict(mtbf_link_s=60000.0, down_s=(20.0, 90.0), intensity=1.0, detect_delay_s=1.0),
  routing=dict(weights=(1.0, 1.0, 1.0), chunks=4, stickiness=0.9, cadence_ticks=5),
  sim=dict(tick_s=0.1, time_scale=20.0, seed=42),
)
```

---

## 16. Acceptance Baselines (sanity numbers every build must meet)

- Orbital period of default sat: 5700–5760 s. Speed ≈ 7.5–7.7 km/s.
- Default topology: avg ISL degree ≥ 3.0; for sampled times over one orbit, every ground-station pair is graph-connected ≥ 95% of the time (if not, tune `max_range`, `max_deg`, or `ATMOS_KM` margin before proceeding).
- Tick compute time (p95) < 80 ms on a laptop; frontend ≥ 50 fps with 120 sats.
- Headless 30-min sim, seed 42, default scenario: Adaptive PDR > Static PDR and Adaptive mean latency ≤ Static mean latency × 1.15 (adaptive may trade a little distance for reliability), recovery time Adaptive < 5 s vs Static > 20 s. If this does not hold, the bug is in the sim — fix it, do not tweak numbers.

---

## 17. Known Pitfalls

1. deck.gl map panning fights with satellite dragging → disable `dragPan` synchronously via `deck.setProps` on pointer-down (not via React state).
2. Longitude wrap: interpolation across ±180° snaps unless you shortest-arc the delta.
3. `nx.dijkstra_path` with a Python-callable weight is slow; use a precomputed `w` edge attribute.
4. Persist failure state by link id, not by list index (links appear/disappear every tick).
5. Don't compute both algorithms on one shared load map — they must have separate loads (§8).
6. Slide-8 style charts must be generated from real benchmark output (MVP phase M6), never typed in by hand.
7. Offline hackathon Wi-Fi: no CDN assets, no map tiles, no web fonts from the network (bundle Inter via `@fontsource/inter`). Run `npm install` / `pip install` once before the event.
