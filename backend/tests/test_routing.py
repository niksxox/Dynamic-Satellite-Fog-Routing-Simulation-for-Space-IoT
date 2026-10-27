"""Unit tests for static and adaptive routing (backend/app/sim/routing/)."""

from typing import Any, Dict, List, Tuple
import math
import time

import networkx as nx
import numpy as np
import pytest

from app.sim.conditions import ConditionModel, FailParams, link_key
from app.sim.orbit import positions_ecef, walker_delta
from app.sim.routing import (
    AdaptiveParams,
    AdaptiveRouter,
    DEFAULT_WEIGHTS,
    StaticRouter,
    link_cost,
)
from app.sim.topology import Topology, build_topology, default_ground_stations
from app.sim.traffic import Flow, default_flows, evaluate


def make_diamond_topo(
    cap_1000: bool = True,
    dist_path2: float = 2000.0,
) -> Tuple[Topology, ConditionModel]:
    """Build diamond topology S(0)->A(1)->D(3) and S(0)->B(2)->D(3).

    ISL links: (0, 1), (1, 3) at 2000 km; (0, 2), (2, 3) at dist_path2 km.
    If cap_1000 is True, cond.link_props is monkeypatched to return capacity_mbps = 1000.0.
    """
    pos = np.zeros((4, 3), dtype=np.float64)
    ground_pos = np.zeros((0, 3), dtype=np.float64)
    dist = {
        (0, 1): 2000.0,
        (1, 3): 2000.0,
        (0, 2): dist_path2,
        (2, 3): dist_path2,
    }
    topo = Topology(
        isl=[(0, 1), (1, 3), (0, 2), (2, 3)],
        gsl=[],
        pos=pos,
        ground_pos=ground_pos,
        dist=dist,
    )
    cond = ConditionModel(
        rng=np.random.default_rng(42),
        params=FailParams(intensity=0.0),
        n_sats=4,
        ground=[],
    )

    if cap_1000:
        # We monkeypatch cond.link_props to return capacity_mbps = 1000.0 on all links
        orig_props = cond.link_props

        def monkey_link_props(t_snap: Topology, a: int, b: int) -> Dict[str, Any]:
            p = orig_props(t_snap, a, b)
            p["capacity_mbps"] = 1000.0
            return p

        cond.link_props = monkey_link_props

    return topo, cond


def test_1_diamond_split_vs_static():
    """1. Diamond S(0)->A(1)->D(3) and S(0)->B(2)->D(3), equal distances, capacity 1000 on all links.

    Monkeypatch cond.link_props to capacity 1000 Mbps.
    A 1500 Mbps flow: adaptive splits across both paths (2 chunks), each ~750; static uses one path.
    """
    topo, cond = make_diamond_topo(cap_1000=True, dist_path2=2000.0)
    flow = Flow(id="F_DIAMOND", src=0, dst=3, mbps=1500.0)

    # Adaptive router with 4 chunks
    adaptive = AdaptiveRouter(cond, AdaptiveParams(chunks=4))
    a_routes = adaptive.update(topo, [flow], t=0.0)
    a_chunks = a_routes["F_DIAMOND"]

    assert len(a_chunks) == 2, f"Expected 2 merged chunks, got {len(a_chunks)}"
    paths = {tuple(p) for p, _ in a_chunks}
    assert (0, 1, 3) in paths
    assert (0, 2, 3) in paths

    for path, rate in a_chunks:
        assert math.isclose(rate, 750.0, abs_tol=1.0), f"Chunk rate {rate} != ~750"

    # Static router uses a single path with full 1500 Mbps
    static = StaticRouter()
    s_routes = static.update(topo, [flow])
    s_chunks = s_routes["F_DIAMOND"]

    assert len(s_chunks) == 1
    assert s_chunks[0][0] in ([0, 1, 3], [0, 2, 3])
    assert math.isclose(s_chunks[0][1], 1500.0)


def test_2_failure_and_detection_delay():
    """2. Failure: fail link S-A.

    Static: its hop is down, so after evaluate() the flow is blackholed (pdr 0) and the static path is unchanged.
    Adaptive: at 0.5 s after the failure it still blackholes; after detect_delay it reroutes via B and evaluate() pdr > 0.9.
    """
    topo, cond = make_diamond_topo(cap_1000=False, dist_path2=2500.0)

    flow = Flow(id="F1", src=0, dst=3, mbps=100.0)

    static = StaticRouter()
    adaptive = AdaptiveRouter(cond, AdaptiveParams(detect_delay_s=1.0))

    # Initial routes at t=0 (routes via S-A-D 0-1-3)
    s_routes0 = static.update(topo, [flow])
    assert s_routes0["F1"][0][0] == [0, 1, 3]

    a_routes0 = adaptive.update(topo, [flow], t=0.0)
    assert a_routes0["F1"][0][0] == [0, 1, 3]

    # Fail link S-A (0, 1) at t=10.0 s
    cond.fail_link(0, 1, t=10.0)

    # At t=10.5 s (0.5 s after failure < detect_delay_s 1.0 s)
    s_routes_10_5 = static.update(topo, [flow])
    assert s_routes_10_5["F1"][0][0] == [0, 1, 3]  # Static path unchanged
    eval_s_10_5 = evaluate(topo, cond, [flow], s_routes_10_5, t=10.5)
    assert eval_s_10_5.flows["F1"].pdr == 0.0  # Flow blackholed

    # Adaptive router without force: failure not visible yet, returns held routes
    a_routes_10_5 = adaptive.update(topo, [flow], t=10.5)
    assert a_routes_10_5["F1"][0][0] == [0, 1, 3]
    eval_a_10_5 = evaluate(topo, cond, [flow], a_routes_10_5, t=10.5)
    assert eval_a_10_5.flows["F1"].pdr == 0.0  # Still blackholes at 0.5 s

    # At t=11.5 s (1.5 s after failure > detect_delay_s 1.0 s)
    # Failure is now visible_down, triggering automatic recomputation
    a_routes_11_5 = adaptive.update(topo, [flow], t=11.5)
    assert all(c[0] == [0, 2, 3] for c in a_routes_11_5["F1"])  # Rerouted via B
    eval_a_11_5 = evaluate(topo, cond, [flow], a_routes_11_5, t=11.5)
    assert eval_a_11_5.flows["F1"].pdr > 0.9, f"Adaptive PDR {eval_a_11_5.flows['F1'].pdr} not > 0.9"


def test_3_hysteresis_noise():
    """3. Hysteresis: add tiny noise to distances (+/-0.5%) for 100 consecutive updates with force=True: adaptive reroutes stay 0."""
    topo, cond = make_diamond_topo(cap_1000=False, dist_path2=2200.0)
    flow = Flow(id="F1", src=0, dst=3, mbps=500.0)

    adaptive = AdaptiveRouter(cond, AdaptiveParams(stickiness=0.9))
    adaptive.update(topo, [flow], t=0.0, force=True)
    assert adaptive.reroutes == 0

    base_dist = dict(topo.dist)
    rng = np.random.default_rng(12345)

    for step in range(100):
        # Perturb distances by +/-0.5%
        for k in base_dist:
            noise_factor = 1.0 + float(rng.uniform(-0.005, 0.005))
            topo.dist[k] = base_dist[k] * noise_factor

        adaptive.update(topo, [flow], t=float(step + 1), force=True)
        assert adaptive.reroutes == 0, f"Reroutes incremented to {adaptive.reroutes} at step {step}"


def test_4_congestion_avoidance():
    """4. Congestion avoidance: when the shorter path is pre-loaded (another flow routed first) adaptive picks the longer uncongested path for the second flow."""
    # Path 1: 0-1-3 (dist 1000 each = 2000 total)
    # Path 2: 0-2-3 (dist 1500 each = 3000 total)
    pos = np.zeros((4, 3), dtype=np.float64)
    ground_pos = np.zeros((0, 3), dtype=np.float64)
    dist = {
        (0, 1): 1000.0,
        (1, 3): 1000.0,
        (0, 2): 1500.0,
        (2, 3): 1500.0,
    }
    topo = Topology(
        isl=[(0, 1), (1, 3), (0, 2), (2, 3)],
        gsl=[],
        pos=pos,
        ground_pos=ground_pos,
        dist=dist,
    )
    cond = ConditionModel(
        rng=np.random.default_rng(42),
        params=FailParams(intensity=0.0),
        n_sats=4,
        ground=[],
    )

    # Pre-loading flow on the shorter path hop (0, 1)
    flow_preload = Flow(id="F_PRELOAD", src=0, dst=1, mbps=1800.0)
    flow_target = Flow(id="F_TARGET", src=0, dst=3, mbps=200.0)

    adaptive = AdaptiveRouter(cond)
    # Flows are sorted descending by mbps: F_PRELOAD routes first, loading (0, 1) to rho=0.9
    routes = adaptive.update(topo, [flow_target, flow_preload], t=0.0, force=True)

    target_path = routes["F_TARGET"][0][0]
    assert target_path == [0, 2, 3], f"Target flow chose {target_path} instead of uncongested [0, 2, 3]"


def test_5_unreachable_destination():
    """5. Unreachable destination: returns [] and does not raise."""
    pos = np.zeros((5, 3), dtype=np.float64)
    ground_pos = np.zeros((0, 3), dtype=np.float64)
    dist = {(0, 1): 1000.0}
    # Node 4 has no links to node 0
    topo = Topology(
        isl=[(0, 1)],
        gsl=[],
        pos=pos,
        ground_pos=ground_pos,
        dist=dist,
    )
    cond = ConditionModel(
        rng=np.random.default_rng(42),
        params=FailParams(intensity=0.0),
        n_sats=5,
        ground=[],
    )
    flow = Flow(id="F_UNREACHABLE", src=0, dst=4, mbps=100.0)

    static = StaticRouter()
    s_routes = static.update(topo, [flow])
    assert s_routes["F_UNREACHABLE"] == []

    adaptive = AdaptiveRouter(cond)
    a_routes = adaptive.update(topo, [flow], t=0.0, force=True)
    assert a_routes["F_UNREACHABLE"] == []


def test_6_ground_transit_rule():
    """6. Ground transit rule: a path never passes through a ground node as an intermediate hop."""
    # Constellation: satellites 0 and 1.
    # Ground stations: G1 (2), G2 (3), G3 (4).
    # G1->S0->G3->S1->G2 is short (1000 + 100 + 100 + 1000 = 2200 km)
    # G1->S0->S1->G2 is long (1000 + 10000 + 1000 = 12000 km)
    # Ground transit rule prohibits transit through G3.
    pos = np.zeros((2, 3), dtype=np.float64)
    ground_pos = np.zeros((3, 3), dtype=np.float64)
    isl = [(0, 1)]
    gsl = [(0, 2), (1, 3), (0, 4), (1, 4)]
    dist = {
        (0, 1): 10000.0,
        (0, 2): 1000.0,
        (1, 3): 1000.0,
        (0, 4): 100.0,
        (1, 4): 100.0,
    }
    topo = Topology(
        isl=isl,
        gsl=gsl,
        pos=pos,
        ground_pos=ground_pos,
        dist=dist,
    )
    cond = ConditionModel(
        rng=np.random.default_rng(42),
        params=FailParams(intensity=0.0),
        n_sats=2,
        ground=[{"id": 2, "name": "G1"}, {"id": 3, "name": "G2"}, {"id": 4, "name": "G3"}],
    )

    flow = Flow(id="F_G1_G2", src=2, dst=3, mbps=100.0)

    static = StaticRouter()
    s_routes = static.update(topo, [flow])
    s_path = s_routes["F_G1_G2"][0][0]
    assert s_path == [2, 0, 1, 3], f"Static used forbidden transit: {s_path}"

    adaptive = AdaptiveRouter(cond)
    a_routes = adaptive.update(topo, [flow], t=0.0, force=True)
    a_path = a_routes["F_G1_G2"][0][0]
    assert a_path == [2, 0, 1, 3], f"Adaptive used forbidden transit: {a_path}"


def test_7_static_ignores_failures():
    """7. Static ignores failures: after failing a hop, static routes for the flow are identical to before."""
    topo, cond = make_diamond_topo(cap_1000=False)
    flow = Flow(id="F1", src=0, dst=3, mbps=100.0)

    static = StaticRouter()
    routes1 = static.update(topo, [flow])
    path1 = routes1["F1"][0][0]

    # Fail the first hop on path1
    u, v = path1[0], path1[1]
    cond.fail_link(u, v, t=0.0)

    routes2 = static.update(topo, [flow])
    path2 = routes2["F1"][0][0]

    assert path1 == path2, f"Static route changed from {path1} to {path2} after failure"
    assert static.reroutes == 0


def test_8_real_default_topology_performance():
    """8. REAL default topology (120 sats, default ground, default flows, el_min as currently set).

    adaptive.update with force=True p95 over 50 runs < 60 ms (print p95).
    Static update p95 print too.
    Assert every flow that has a physical path gets a non-empty route from both routers at t=0;
    if some flows have no physical path at t=0, print which ones and do NOT fail the test,
    but assert at least 4 of 8 are routable.
    """
    constellation = walker_delta(120, 12, 1, 53, 550)
    pos = positions_ecef(constellation, 0.0)
    ground = default_ground_stations(120)
    topo = build_topology(pos, ground)
    cond = ConditionModel(np.random.default_rng(42), FailParams(), 120, ground)
    flows = default_flows(ground)

    # 1. Benchmark AdaptiveRouter
    adaptive = AdaptiveRouter(cond)
    # Warm-up
    _ = adaptive.update(topo, flows, t=0.0, force=True)

    a_times = []
    for _ in range(50):
        t0 = time.perf_counter()
        _ = adaptive.update(topo, flows, t=0.0, force=True)
        a_times.append((time.perf_counter() - t0) * 1000.0)

    a_p95 = float(np.percentile(a_times, 95))
    print(f"\nAdaptiveRouter update p95: {a_p95:.2f} ms")
    assert a_p95 < 60.0, f"AdaptiveRouter p95 {a_p95:.2f} ms not < 60 ms"

    # 2. Benchmark StaticRouter
    static = StaticRouter()
    # Warm-up
    _ = static.update(topo, flows)

    s_times = []
    for _ in range(50):
        t0 = time.perf_counter()
        _ = static.update(topo, flows)
        s_times.append((time.perf_counter() - t0) * 1000.0)

    s_p95 = float(np.percentile(s_times, 95))
    print(f"StaticRouter update p95: {s_p95:.2f} ms")

    # 3. Routability check
    G_phys = nx.Graph()
    for u, v in topo.isl + topo.gsl:
        G_phys.add_edge(u, v)

    ground_nodes = set(range(120, 130))
    s_routes = static.update(topo, flows)
    a_routes = adaptive.update(topo, flows, t=0.0, force=True)

    routable_count = 0
    for f in flows:
        forbidden = ground_nodes - {f.src, f.dst}
        sub = G_phys.subgraph([n for n in G_phys if n not in forbidden])
        has_path = nx.has_path(sub, f.src, f.dst) if (f.src in sub and f.dst in sub) else False

        if has_path:
            routable_count += 1
            assert len(s_routes[f.id]) > 0, f"Static route empty for routable flow {f.id}"
            assert len(a_routes[f.id]) > 0, f"Adaptive route empty for routable flow {f.id}"
        else:
            print(f"Flow {f.id} has no physical path at t=0")

    print(f"Routable flows at t=0: {routable_count}/{len(flows)}")
    assert routable_count >= 4, f"Only {routable_count} of {len(flows)} flows routable at t=0"
