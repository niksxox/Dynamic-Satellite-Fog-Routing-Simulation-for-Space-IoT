"""Unit tests for traffic flow modeling and path evaluation (backend/app/sim/traffic.py)."""

import math
import time
from typing import Dict, Tuple

import numpy as np
import pytest

from app.sim.conditions import ConditionModel, FailParams, link_key
from app.sim.linkmath import link_latency_ms, prop_ms, queue_ms, survive
from app.sim.orbit import positions_ecef, walker_delta
from app.sim.topology import Topology, build_topology, default_ground_stations
from app.sim.traffic import (
    EvalResult,
    Flow,
    FlowEval,
    default_flows,
    evaluate,
)


def make_3node_topo() -> Tuple[Topology, ConditionModel]:
    """Construct a hand-built 3-node line topology 0-1-2 with distance 3000 km per hop."""
    pos = np.zeros((3, 3), dtype=np.float64)
    ground_pos = np.zeros((0, 3), dtype=np.float64)
    dist = {
        (0, 1): 3000.0,
        (1, 2): 3000.0,
    }
    topo = Topology(
        isl=[(0, 1), (1, 2)],
        gsl=[],
        pos=pos,
        ground_pos=ground_pos,
        dist=dist,
    )
    cond = ConditionModel(
        rng=np.random.default_rng(42),
        params=FailParams(intensity=0.0),
        n_sats=3,
        ground=[],
    )
    return topo, cond


def test_1_light_load():
    """1. Light load (100 Mbps over 0-1-2): pdr ~= 0.999*0.999, ms = 2*(prop_ms(3000)+0.3+queue_ms(0.05)) within 0.01."""
    topo, cond = make_3node_topo()
    flow = Flow(id="F1", src=0, dst=2, mbps=100.0)
    routes = {"F1": [([0, 1, 2], 100.0)]}

    res = evaluate(topo, cond, [flow], routes, t=0.0)
    fe = res.flows["F1"]

    expected_pdr = 0.999 * 0.999
    assert math.isclose(fe.pdr, expected_pdr, rel_tol=1e-5), f"PDR {fe.pdr} != {expected_pdr}"

    expected_ms = 2.0 * (prop_ms(3000.0) + 0.3 + queue_ms(0.05))
    assert abs(fe.ms - expected_ms) <= 0.01, f"Latency {fe.ms} ms not within 0.01 of {expected_ms} ms"
    assert not fe.blackholed
    assert math.isclose(fe.delivered_mbps, 100.0 * expected_pdr, rel_tol=1e-5)


def test_2_overload():
    """2. Overload: 3000 Mbps over 0-1-2 (rho 1.5 on both hops): delivered ~= 3000 * s * s where s = linkmath.survive(1.5); pdr < 0.5."""
    topo, cond = make_3node_topo()
    flow = Flow(id="F1", src=0, dst=2, mbps=3000.0)
    routes = {"F1": [([0, 1, 2], 3000.0)]}

    res = evaluate(topo, cond, [flow], routes, t=0.0)
    fe = res.flows["F1"]

    s = float(survive(1.5))
    expected_delivered = 3000.0 * s * s
    assert math.isclose(fe.delivered_mbps, expected_delivered, rel_tol=1e-5), f"Delivered {fe.delivered_mbps} != {expected_delivered}"
    assert fe.pdr < 0.5, f"PDR {fe.pdr} not < 0.5"
    assert math.isclose(fe.pdr, s * s, rel_tol=1e-5)
    assert not fe.blackholed


def test_3_two_flows_shared_link():
    """3. Two flows share link 1-2: its load is the sum and rho reflects it; the first link carries only its own flow."""
    topo, cond = make_3node_topo()
    flow1 = Flow(id="F1", src=0, dst=2, mbps=200.0)
    flow2 = Flow(id="F2", src=1, dst=2, mbps=300.0)
    routes = {
        "F1": [([0, 1, 2], 200.0)],
        "F2": [([1, 2], 300.0)],
    }

    res = evaluate(topo, cond, [flow1, flow2], routes, t=0.0)

    # Link (0, 1) carries only F1: load = 200, capacity = 2000
    assert res.links[(0, 1)]["load"] == 200.0
    assert math.isclose(res.links[(0, 1)]["rho"], 200.0 / 2000.0, rel_tol=1e-5)

    # Link (1, 2) carries both F1 and F2: load = 500, capacity = 2000
    assert res.links[(1, 2)]["load"] == 500.0
    assert math.isclose(res.links[(1, 2)]["rho"], 500.0 / 2000.0, rel_tol=1e-5)


def test_4_hop_down_and_absent():
    """4. Hop down (cond.fail_link(1,2,0)): flow blackholed, delivered 0, pdr 0; hop absent from topo: also blackholed; blackholed chunk does not add load."""
    topo, cond = make_3node_topo()
    cond.fail_link(1, 2, t=0.0)

    flow = Flow(id="F1", src=0, dst=2, mbps=100.0)
    routes = {"F1": [([0, 1, 2], 100.0)]}

    res = evaluate(topo, cond, [flow], routes, t=0.0)
    fe = res.flows["F1"]

    assert fe.blackholed is True
    assert fe.delivered_mbps == 0.0
    assert fe.pdr == 0.0
    # Blackholed chunk does not add load to any link
    assert res.links[(0, 1)]["load"] == 0.0
    assert res.links[(1, 2)]["load"] == 0.0
    assert res.links[(1, 2)]["up"] is False

    # Hop absent from topology
    cond.restore_link(1, 2, t=0.0)
    flow_absent = Flow(id="F2", src=0, dst=2, mbps=100.0)
    # Hop (0, 2) does not exist in topo.isl or topo.gsl
    routes_absent = {"F2": [([0, 2], 100.0)]}

    res_absent = evaluate(topo, cond, [flow_absent], routes_absent, t=0.0)
    fe_absent = res_absent.flows["F2"]

    assert fe_absent.blackholed is True
    assert fe_absent.delivered_mbps == 0.0
    assert fe_absent.pdr == 0.0
    assert res_absent.links[(0, 1)]["load"] == 0.0
    assert res_absent.links[(1, 2)]["load"] == 0.0


def test_5_split_flow():
    """5. Split flow: two chunks of 500 over different paths in a 4-node diamond -> flow.paths has both, delivered sums, ms is delivered-weighted."""
    # 4-node diamond: 0 connected to 1 and 2; 1 and 2 connected to 3.
    pos = np.zeros((4, 3), dtype=np.float64)
    ground_pos = np.zeros((0, 3), dtype=np.float64)
    dist = {
        (0, 1): 2000.0,
        (1, 3): 2000.0,
        (0, 2): 4000.0,
        (2, 3): 4000.0,
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

    flow = Flow(id="F_SPLIT", src=0, dst=3, mbps=1000.0)
    chunk1 = ([0, 1, 3], 500.0)
    chunk2 = ([0, 2, 3], 500.0)
    routes = {"F_SPLIT": [chunk1, chunk2]}

    res = evaluate(topo, cond, [flow], routes, t=0.0)
    fe = res.flows["F_SPLIT"]

    assert len(fe.paths) == 2
    assert fe.paths[0] == chunk1
    assert fe.paths[1] == chunk2
    assert not fe.blackholed

    # Calculate expected delivered & latencies
    rho = 500.0 / 2000.0  # 0.25
    s = float(survive(rho))
    del1 = 500.0 * s * s
    del2 = 500.0 * s * s
    assert math.isclose(fe.delivered_mbps, del1 + del2, rel_tol=1e-5)

    ms1 = 2.0 * float(link_latency_ms(prop_ms(2000.0), rho))
    ms2 = 2.0 * float(link_latency_ms(prop_ms(4000.0), rho))
    expected_ms = (del1 * ms1 + del2 * ms2) / (del1 + del2)
    assert math.isclose(fe.ms, expected_ms, rel_tol=1e-5)


def test_6_no_routes_entry():
    """6. No routes entry -> blackholed True, pdr 0."""
    topo, cond = make_3node_topo()
    flow = Flow(id="F_EMPTY", src=0, dst=2, mbps=100.0)
    routes = {}

    res = evaluate(topo, cond, [flow], routes, t=0.0)
    fe = res.flows["F_EMPTY"]

    assert fe.blackholed is True
    assert fe.pdr == 0.0
    assert fe.delivered_mbps == 0.0
    assert fe.ms == 0.0
    assert fe.paths == []


def test_7_totals():
    """7. Totals: thr_mbps equals the sum of flow delivered; pdr equals thr/offered."""
    topo, cond = make_3node_topo()
    f1 = Flow(id="F1", src=0, dst=2, mbps=100.0)
    f2 = Flow(id="F2", src=1, dst=2, mbps=200.0)
    f3 = Flow(id="F3", src=0, dst=1, mbps=300.0)  # Unrouted

    routes = {
        "F1": [([0, 1, 2], 100.0)],
        "F2": [([1, 2], 200.0)],
    }

    res = evaluate(topo, cond, [f1, f2, f3], routes, t=0.0)

    delivered_sum = sum(fe.delivered_mbps for fe in res.flows.values())
    assert math.isclose(res.thr_mbps, delivered_sum, rel_tol=1e-5)

    total_offered = 100.0 + 200.0 + 300.0
    expected_pdr = delivered_sum / total_offered
    assert math.isclose(res.pdr, expected_pdr, rel_tol=1e-5)

    expected_lat = (
        sum(fe.delivered_mbps * fe.ms for fe in res.flows.values()) / delivered_sum
    )
    assert math.isclose(res.lat_ms, expected_lat, rel_tol=1e-5)


def test_8_default_flows():
    """8. default_flows returns 8 flows with the right ids and rates, using real default ground stations."""
    ground = default_ground_stations(120)
    flows = default_flows(ground)

    assert len(flows) == 8

    # Ground stations start at 120:
    # 120 Delhi (DEL), 121 London (LON), 122 New York (NYC), 123 Sao Paulo (SAO),
    # 124 Johannesburg (JNB), 125 Tokyo (TYO), 126 Sydney (SYD), 127 Singapore (SIN),
    # 128 Dubai (DXB), 129 Los Angeles (LAX)
    station_lookup = {gs.name: gs.id for gs in ground}

    expected_specs = [
        ("DEL-LON", station_lookup["Delhi"], station_lookup["London"], 600.0),
        ("NYC-SIN", station_lookup["New York"], station_lookup["Singapore"], 500.0),
        ("LAX-TYO", station_lookup["Los Angeles"], station_lookup["Tokyo"], 400.0),
        ("SAO-JNB", station_lookup["Sao Paulo"], station_lookup["Johannesburg"], 300.0),
        ("DXB-SYD", station_lookup["Dubai"], station_lookup["Sydney"], 350.0),
        ("LON-NYC", station_lookup["London"], station_lookup["New York"], 700.0),
        ("SIN-SYD", station_lookup["Singapore"], station_lookup["Sydney"], 450.0),
        ("DEL-TYO", station_lookup["Delhi"], station_lookup["Tokyo"], 400.0),
    ]

    for flow, (exp_id, exp_src, exp_dst, exp_rate) in zip(flows, expected_specs):
        assert flow.id == exp_id
        assert flow.src == exp_src
        assert flow.dst == exp_dst
        assert math.isclose(flow.mbps, exp_rate)


def test_9_smoke_real_default_topology():
    """9. Smoke test on the REAL default topology at t=0 (120 sats, default ground): evaluate() with routes={} runs without error and takes < 20 ms."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    pos = positions_ecef(constellation, 0.0)
    ground = default_ground_stations(120)
    topo = build_topology(pos, ground)
    cond = ConditionModel(np.random.default_rng(42), FailParams(), 120, ground)
    flows = default_flows(ground)

    # Warm-up call
    _ = evaluate(topo, cond, flows, routes={}, t=0.0)

    # Timed evaluation
    t0 = time.perf_counter()
    res = evaluate(topo, cond, flows, routes={}, t=0.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\nSmoke test evaluate() execution time on real topology: {elapsed_ms:.3f} ms")
    assert elapsed_ms < 20.0, f"evaluate() took {elapsed_ms:.3f} ms >= 20 ms"

    # Verifications
    assert len(res.flows) == 8
    all_links = set(link_key(u, v) for u, v in (topo.isl + topo.gsl))
    assert len(res.links) == len(all_links)

    for fe in res.flows.values():
        assert fe.blackholed is True
        assert fe.delivered_mbps == 0.0
        assert fe.pdr == 0.0
        assert fe.ms == 0.0
        assert fe.paths == []

    assert res.thr_mbps == 0.0
    assert res.pdr == 0.0
    assert res.lat_ms == 0.0
