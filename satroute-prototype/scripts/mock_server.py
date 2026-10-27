"""Mock WebSocket server for Person 2 (Frontend) development.
Follows docs/SPEC.md §12 and validates all outgoing messages against backend/app/schemas.py.
"""

import asyncio
import math
import random
import time
from typing import Dict, List, Set, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import sys
from pathlib import Path

# Add backend to path so schemas can be imported
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.schemas import (
    InitMessage, FrameMessage, AckResponse, ErrorResponse, OrbitPreviewResponse,
    SimConfig, GroundStation, Flow, SatState, LinkState, FlowPair, FlowEval,
    PathChunk, Metrics, OverallMetrics, SimEvent
)

app = FastAPI(title="SatRoute Mock Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
N_SATS = 120
N_PLANES = 12
SATS_PER_PLANE = 10
INCLINATION_RAD = math.radians(53.0)
PERIOD_S = 5730.0
OMEGA_ORBIT = 2 * math.pi / PERIOD_S
OMEGA_EARTH = 7.2921159e-5
DEFAULT_SCALE = 20.0
ALT_KM = 550.0

# 10 Ground Stations from SPEC §8
DEFAULT_GROUND = [
    GroundStation(id=120, name="Delhi", lat=28.61, lon=77.21),
    GroundStation(id=121, name="London", lat=51.51, lon=-0.13),
    GroundStation(id=122, name="New York", lat=40.71, lon=-74.01),
    GroundStation(id=123, name="Los Angeles", lat=34.05, lon=-118.24),
    GroundStation(id=124, name="São Paulo", lat=-23.55, lon=-46.63),
    GroundStation(id=125, name="Johannesburg", lat=-26.20, lon=28.05),
    GroundStation(id=126, name="Dubai", lat=25.20, lon=55.27),
    GroundStation(id=127, name="Singapore", lat=1.35, lon=103.82),
    GroundStation(id=128, name="Tokyo", lat=35.68, lon=139.69),
    GroundStation(id=129, name="Sydney", lat=-33.87, lon=151.21),
]

# 8 Flows from SPEC §8
DEFAULT_FLOWS = [
    Flow(id="DEL->LON", src_gs=120, dst_gs=121, mbps=600.0),
    Flow(id="NYC->SIN", src_gs=122, dst_gs=127, mbps=500.0),
    Flow(id="LAX->TYO", src_gs=123, dst_gs=128, mbps=400.0),
    Flow(id="SAO->JNB", src_gs=124, dst_gs=125, mbps=300.0),
    Flow(id="DXB->SYD", src_gs=126, dst_gs=129, mbps=350.0),
    Flow(id="LON->NYC", src_gs=121, dst_gs=122, mbps=700.0),
    Flow(id="SIN->SYD", src_gs=127, dst_gs=129, mbps=450.0),
    Flow(id="DEL->TYO", src_gs=120, dst_gs=128, mbps=400.0),
]

class MockState:
    def __init__(self):
        self.t = 0.0
        self.scale = DEFAULT_SCALE
        self.running = True
        self.planes = []
        self.u0 = []
        self.raan = []
        self.sat_status: List[int] = [0] * N_SATS  # 0 ok, 1 down, 2 eclipse, 3 manual
        self.down_links: Dict[Tuple[int, int], float] = {}  # (a,b) -> down_until_t
        self.flow_scale = 1.0
        self.events: List[SimEvent] = []
        self.link_rhos: Dict[Tuple[int, int], float] = {}
        self.adaptive_reroute_count = 0
        self.static_reroute_count = 0
        self.failed_at: Dict[Tuple[int, int], float] = {}

        # Setup Walker constellation orbit angles
        for p in range(N_PLANES):
            for s in range(SATS_PER_PLANE):
                self.planes.append(p)
                self.raan.append(2 * math.pi * p / N_PLANES)
                self.u0.append((2 * math.pi * s / SATS_PER_PLANE + 2 * math.pi * 1 * p / N_SATS) % (2 * math.pi))

    def get_sat_pos(self, sat_id: int, t_sim: float) -> Tuple[float, float, float, float]:
        """Compute lat, lon, vlat, vlon (deg/wall-sec) for sat."""
        u = self.u0[sat_id] + OMEGA_ORBIT * t_sim
        raan = self.raan[sat_id]
        inc = INCLINATION_RAD

        sin_lat = math.sin(inc) * math.sin(u)
        lat_rad = math.asin(max(-1.0, min(1.0, sin_lat)))

        # Longitude in rotating frame
        lam_inertial = raan + math.atan2(math.cos(inc) * math.sin(u), math.cos(u))
        lon_rad = (lam_inertial - OMEGA_EARTH * t_sim + math.pi) % (2 * math.pi) - math.pi

        lat_deg = math.degrees(lat_rad)
        lon_deg = math.degrees(lon_rad)

        # Derivatives per sim second
        dlat_dt_sim = (OMEGA_ORBIT * math.cos(inc) * math.cos(u)) / max(0.1, math.cos(lat_rad))
        dlon_dt_sim = (OMEGA_ORBIT * math.cos(inc) / (max(0.1, math.cos(lat_rad)) ** 2)) - OMEGA_EARTH

        # Deg per wall second
        vlat = math.degrees(dlat_dt_sim) * self.scale
        vlon = math.degrees(dlon_dt_sim) * self.scale

        return lat_deg, lon_deg, vlat, vlon

mock_sim = MockState()

def build_mock_init() -> InitMessage:
    return InitMessage(
        config=SimConfig(),
        ground=DEFAULT_GROUND,
        flows=DEFAULT_FLOWS,
        nSats=N_SATS,
        planes=mock_sim.planes,
    )

def bfs_path(adj: Dict[int, List[int]], src: int, dst: int, avoid_edges: Set[Tuple[int, int]] = None) -> List[int]:
    """Find shortest path via BFS."""
    if avoid_edges is None:
        avoid_edges = set()
    queue = [[src]]
    visited = {src}
    while queue:
        path = queue.pop(0)
        curr = path[-1]
        if curr == dst:
            return path
        for nbr in adj.get(curr, []):
            edge = (min(curr, nbr), max(curr, nbr))
            if nbr not in visited and edge not in avoid_edges:
                visited.add(nbr)
                queue.append(path + [nbr])
    return []

def step_simulation(dt_wall: float = 0.1) -> FrameMessage:
    t_start = time.perf_counter()
    if mock_sim.running:
        mock_sim.t += dt_wall * mock_sim.scale

    # Compute satellites
    sats: List[SatState] = []
    for i in range(N_SATS):
        lat, lon, vlat, vlon = mock_sim.get_sat_pos(i, mock_sim.t)
        sats.append(
            SatState(
                id=i,
                lat=round(lat, 4),
                lon=round(lon, 4),
                alt=ALT_KM,
                vlat=round(vlat, 4),
                vlon=round(vlon, 4),
                st=mock_sim.sat_status[i],
            )
        )

    # Expire down links
    restored_links = []
    for link, down_until in list(mock_sim.down_links.items()):
        if mock_sim.t >= down_until:
            restored_links.append(link)
            del mock_sim.down_links[link]
            mock_sim.events.append(
                SimEvent(
                    t=round(mock_sim.t, 2),
                    level="info",
                    kind="link_restore",
                    msg=f"Link {link[0]}-{link[1]} auto-restored",
                )
            )

    # Topology & Links:
    # 1. In-plane ISL + 1 cross-plane ISL
    links: List[LinkState] = []
    adj: Dict[int, List[int]] = {i: [] for i in range(N_SATS + len(DEFAULT_GROUND))}

    for p in range(N_PLANES):
        for s in range(SATS_PER_PLANE):
            i = p * SATS_PER_PLANE + s
            # In-plane next
            nxt = p * SATS_PER_PLANE + ((s + 1) % SATS_PER_PLANE)
            # Cross plane
            cross = ((p + 1) % N_PLANES) * SATS_PER_PLANE + s

            for peer in [nxt, cross]:
                link_key = (min(i, peer), max(i, peer))
                is_up = 1 if link_key not in mock_sim.down_links and mock_sim.sat_status[i] == 0 and mock_sim.sat_status[peer] == 0 else 0

                # Random walk rho
                prev_rho = mock_sim.link_rhos.get(link_key, 0.35)
                rho = max(0.1, min(0.95, prev_rho + (random.random() - 0.5) * 0.05))
                mock_sim.link_rhos[link_key] = rho

                links.append(
                    LinkState(
                        a=link_key[0],
                        b=link_key[1],
                        k=0,
                        up=is_up,
                        rho=round(rho, 3),
                        ms=round(12.0 + rho * 4.0, 1),
                        loss=0.001 if is_up else 1.0,
                    )
                )
                if is_up:
                    adj[link_key[0]].append(link_key[1])
                    adj[link_key[1]].append(link_key[0])

    # 2. GSL: 3 nearest sats to each ground station
    for gs in DEFAULT_GROUND:
        # Pick 3 satellites with closest lat/lon
        dist_sats = []
        for s in sats:
            d_lat = s.lat - gs.lat
            d_lon = (s.lon - gs.lon + 180) % 360 - 180
            dist = math.hypot(d_lat, d_lon)
            dist_sats.append((dist, s.id))
        dist_sats.sort()

        for _, sat_id in dist_sats[:3]:
            link_key = (min(sat_id, gs.id), max(sat_id, gs.id))
            is_up = 1 if link_key not in mock_sim.down_links and mock_sim.sat_status[sat_id] == 0 else 0
            rho = round(random.uniform(0.2, 0.6) * mock_sim.flow_scale, 2)
            links.append(
                LinkState(
                    a=link_key[0],
                    b=link_key[1],
                    k=1,
                    up=is_up,
                    rho=min(0.98, rho),
                    ms=round(4.0 + rho * 2.0, 1),
                    loss=0.001 if is_up else 1.0,
                )
            )
            if is_up:
                adj[link_key[0]].append(link_key[1])
                adj[link_key[1]].append(link_key[0])

    # Compute flows
    flows_eval: List[FlowPair] = []
    avoid_edges = {link for link, rho in mock_sim.link_rhos.items() if rho > 0.85}

    for f in DEFAULT_FLOWS:
        # Static path: BFS on full physical graph (ignoring failures)
        # Adaptive path: BFS avoiding down links & high rho links
        static_p = bfs_path(adj, f.src_gs, f.dst_gs)
        adaptive_p = bfs_path(adj, f.src_gs, f.dst_gs, avoid_edges=avoid_edges)
        if not adaptive_p:
            adaptive_p = bfs_path(adj, f.src_gs, f.dst_gs)

        # Check if static path is currently interrupted
        static_interrupted = False
        if static_p:
            for k in range(len(static_p) - 1):
                e = (min(static_p[k], static_p[k+1]), max(static_p[k], static_p[k+1]))
                if e in mock_sim.down_links:
                    # Check if failure was recent (detect delay)
                    static_interrupted = True
                    break
        else:
            static_interrupted = True

        # Adaptive handles fail with delay of 1.5s
        adaptive_interrupted = False
        if adaptive_p:
            for k in range(len(adaptive_p) - 1):
                e = (min(adaptive_p[k], adaptive_p[k+1]), max(adaptive_p[k], adaptive_p[k+1]))
                if e in mock_sim.down_links:
                    fail_t = mock_sim.failed_at.get(e, mock_sim.t)
                    if (mock_sim.t - fail_t) < 1.5:
                        adaptive_interrupted = True
                    else:
                        # Reroute!
                        adaptive_p = bfs_path(adj, f.src_gs, f.dst_gs, avoid_edges={e})
                        mock_sim.adaptive_reroute_count += 1
                        mock_sim.events.append(
                            SimEvent(
                                t=round(mock_sim.t, 2),
                                level="info",
                                kind="reroute",
                                msg=f"Adaptive rerouted flow {f.id}",
                            )
                        )
                        break

        flows_eval.append(
            FlowPair(
                id=f.id,
                adaptive=FlowEval(
                    paths=[PathChunk(nodes=adaptive_p, mbps=f.mbps * mock_sim.flow_scale)] if adaptive_p else [],
                    ms=round(22.0 + len(adaptive_p) * 4.2, 1) if adaptive_p else 0.0,
                    pdr=0.0 if adaptive_interrupted or not adaptive_p else 0.998,
                    blackholed=adaptive_interrupted or not adaptive_p,
                ),
                static=FlowEval(
                    paths=[PathChunk(nodes=static_p, mbps=f.mbps * mock_sim.flow_scale)] if static_p else [],
                    ms=round(24.0 + len(static_p) * 4.5, 1) if static_p else 0.0,
                    pdr=0.0 if static_interrupted or not static_p else 0.995,
                    blackholed=static_interrupted or not static_p,
                ),
            )
        )

    # Compute overall metrics
    active_failures = len(mock_sim.down_links) + sum(1 for s in mock_sim.sat_status if s != 0)
    adaptive_pdr = sum(f.adaptive.pdr for f in flows_eval) / len(flows_eval)
    static_pdr = sum(f.static.pdr for f in flows_eval) / len(flows_eval)

    metrics = OverallMetrics(
        adaptive=Metrics(
            latMs=round(28.5 + (1.0 - adaptive_pdr) * 10, 1),
            pdr=round(adaptive_pdr, 4),
            thrMbps=round(3700.0 * adaptive_pdr * mock_sim.flow_scale, 1),
            reroutes=mock_sim.adaptive_reroute_count,
            rerouteRate=round(mock_sim.adaptive_reroute_count / max(1.0, mock_sim.t / 60.0), 2),
            recoverS=1.5,
        ),
        static=Metrics(
            latMs=round(32.4 + (1.0 - static_pdr) * 20, 1),
            pdr=round(static_pdr, 4),
            thrMbps=round(3700.0 * static_pdr * mock_sim.flow_scale, 1),
            reroutes=mock_sim.static_reroute_count,
            rerouteRate=0.0,
            recoverS=40.0,
        ),
        linkUptime=round(max(0.7, 1.0 - (active_failures * 0.015)), 3),
        activeFailures=active_failures,
    )

    events_to_send = list(mock_sim.events)
    mock_sim.events.clear()

    tick_ms = round((time.perf_counter() - t_start) * 1000, 2)

    frame = FrameMessage(
        type="frame",
        t=round(mock_sim.t, 2),
        scale=mock_sim.scale,
        running=mock_sim.running,
        tickMs=tick_ms,
        sats=sats,
        links=links,
        flows=flows_eval,
        metrics=metrics,
        events=events_to_send,
    )
    return frame

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # 1. Send Init
    init_msg = build_mock_init()
    await websocket.send_text(init_msg.model_dump_json())

    # 2. Start streaming 10 Hz
    async def send_loop():
        try:
            while True:
                await asyncio.sleep(0.1)
                frame = step_simulation(0.1)
                await websocket.send_text(frame.model_dump_json())
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    task = asyncio.create_task(send_loop())

    try:
        while True:
            text = await websocket.receive_text()
            import json
            data = json.loads(text)
            cmd = data.get("cmd", "")
            args = data.get("args", {})
            cmd_id = data.get("id")

            # Handle Commands
            if cmd == "play":
                mock_sim.running = True
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "pause":
                mock_sim.running = False
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "reset":
                mock_sim.t = 0.0
                mock_sim.down_links.clear()
                mock_sim.sat_status = [0] * N_SATS
                mock_sim.adaptive_reroute_count = 0
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "set_scale":
                mock_sim.scale = float(args.get("scale", 20.0))
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "set_flow_scale":
                mock_sim.flow_scale = float(args.get("factor", 1.0))
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "set_weights":
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "fail_link":
                a = int(args.get("a", 0))
                b = int(args.get("b", 1))
                link_key = (min(a, b), max(a, b))
                mock_sim.down_links[link_key] = mock_sim.t + 40.0
                mock_sim.failed_at[link_key] = mock_sim.t
                mock_sim.events.append(
                    SimEvent(
                        t=round(mock_sim.t, 2),
                        level="warn",
                        kind="link_fail",
                        msg=f"Link {link_key[0]}-{link_key[1]} failed manually",
                    )
                )
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "restore_link":
                a = int(args.get("a", 0))
                b = int(args.get("b", 1))
                link_key = (min(a, b), max(a, b))
                mock_sim.down_links.pop(link_key, None)
                mock_sim.events.append(
                    SimEvent(
                        t=round(mock_sim.t, 2),
                        level="info",
                        kind="link_restore",
                        msg=f"Link {link_key[0]}-{link_key[1]} restored manually",
                    )
                )
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "fail_sat":
                sat_id = int(args.get("id", 0))
                if 0 <= sat_id < N_SATS:
                    mock_sim.sat_status[sat_id] = 1
                    mock_sim.events.append(
                        SimEvent(
                            t=round(mock_sim.t, 2),
                            level="crit",
                            kind="sat_fail",
                            msg=f"Satellite S{sat_id:03d} failed",
                        )
                    )
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "restore_sat":
                sat_id = int(args.get("id", 0))
                if 0 <= sat_id < N_SATS:
                    mock_sim.sat_status[sat_id] = 0
                    mock_sim.events.append(
                        SimEvent(
                            t=round(mock_sim.t, 2),
                            level="info",
                            kind="sat_restore",
                            msg=f"Satellite S{sat_id:03d} restored",
                        )
                    )
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "move_sat":
                sat_id = int(args.get("id", 0))
                lat = float(args.get("lat", 0.0))
                lon = float(args.get("lon", 0.0))
                # Re-fit phase
                phi, lam = math.radians(lat), math.radians(lon)
                inc = INCLINATION_RAD
                if abs(phi) > inc:
                    inc = abs(phi)
                s = max(-1.0, min(1.0, math.sin(phi) / math.sin(inc)))
                u = math.asin(s)
                lam_i = lam + OMEGA_EARTH * mock_sim.t
                raan = lam_i - math.atan2(math.cos(inc) * math.sin(u), math.cos(u))
                mock_sim.raan[sat_id] = raan % (2 * math.pi)
                mock_sim.u0[sat_id] = (u - OMEGA_ORBIT * mock_sim.t) % (2 * math.pi)
                mock_sim.sat_status[sat_id] = 0
                mock_sim.events.append(
                    SimEvent(
                        t=round(mock_sim.t, 2),
                        level="info",
                        kind="move_sat",
                        msg=f"Satellite S{sat_id:03d} moved to ({lat:.1f}, {lon:.1f})",
                    )
                )
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "move_gs":
                gs_id = int(args.get("id", 120))
                lat = float(args.get("lat", 0.0))
                lon = float(args.get("lon", 0.0))
                for gs in DEFAULT_GROUND:
                    if gs.id == gs_id:
                        gs.lat = lat
                        gs.lon = lon
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())
            elif cmd == "preview_orbit":
                sat_id = int(args.get("id", 0))
                track = []
                for step in range(0, 5700, 150):
                    p_lat, p_lon, _, _ = mock_sim.get_sat_pos(sat_id, mock_sim.t + step)
                    track.append((round(p_lon, 2), round(p_lat, 2)))
                await websocket.send_text(OrbitPreviewResponse(id=sat_id, track=track).model_dump_json())
            else:
                await websocket.send_text(AckResponse(id=cmd_id).model_dump_json())

    except (WebSocketDisconnect, asyncio.CancelledError):
        task.cancel()

if __name__ == "__main__":
    uvicorn.run("mock_server:app", host="0.0.0.0", port=8000, reload=False)
