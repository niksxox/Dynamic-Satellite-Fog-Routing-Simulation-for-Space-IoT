"""Unit tests for ISL topology construction backend/app/sim/topology.py."""

import time
import numpy as np
import pytest

from app.sim.constants import ISL_MAX_DEGREE, ISL_MAX_RANGE_KM
from app.sim.orbit import positions_ecef, rephase_to, walker_delta
from app.sim.topology import (
    TopoParams,
    build_isl,
    build_topology,
    default_ground_stations,
)


def test_1_isl_constraints():
    """1. No ISL longer than 5000 km; no node has more than 4 ISLs; no duplicates; every link has i < j."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    pos = positions_ecef(constellation, 0.0)
    ground = default_ground_stations(120)
    params = TopoParams()

    topo = build_topology(pos, ground, prev=None, params=params)

    assert len(topo.isl) > 0, "ISL list should not be empty"

    # Check no duplicates
    assert len(topo.isl) == len(set(topo.isl)), "ISL links contain duplicates"

    degrees = np.zeros(len(pos), dtype=int)
    for u, v in topo.isl:
        # Every link has i < j
        assert u < v, f"Link ({u}, {v}) does not satisfy i < j"
        # Distance within max range (5000 km)
        d = topo.dist[(u, v)]
        assert d <= params.isl_max_range_km, f"Link ({u}, {v}) length {d} km exceeds max range {params.isl_max_range_km}"
        degrees[u] += 1
        degrees[v] += 1

    # No node has more than 4 ISLs
    max_node_deg = int(np.max(degrees))
    assert max_node_deg <= params.max_deg, f"Max node degree {max_node_deg} exceeds {params.max_deg}"


def test_2_hysteresis():
    """2. Hysteresis: build at t=0, then at t=2 passing the first topology as prev;

    at least 95% of the t=0 links are still present at t=2 (print the actual percentage).
    """
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)

    pos_t0 = positions_ecef(constellation, 0.0)
    topo_t0 = build_topology(pos_t0, ground, prev=None)

    pos_t2 = positions_ecef(constellation, 2.0)
    topo_t2 = build_topology(pos_t2, ground, prev=topo_t0)

    links_t0 = set(topo_t0.isl)
    links_t2 = set(topo_t2.isl)

    retained = links_t0.intersection(links_t2)
    percentage = (len(retained) / len(links_t0)) * 100.0

    print(f"\nHysteresis retention from t=0 to t=2: {percentage:.2f}% ({len(retained)}/{len(links_t0)} links retained)")
    assert percentage >= 95.0, f"Link retention {percentage:.2f}% is below 95%"


def test_3_dragged_satellite():
    """3. Dragged satellite: use rephase_to to move one satellite (index 37) to lat 10, lon 60 at t=500,

    rebuild; satellite 37 has at least 1 ISL (print how many).
    """
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)

    # Rephase sat 37 to target location at t=500
    rephase_to(constellation, 37, lat_deg=10.0, lon_deg=60.0, t=500.0)

    pos_t500 = positions_ecef(constellation, 500.0)
    topo = build_topology(pos_t500, ground, prev=None)

    sat_37_links = [link for link in topo.isl if 37 in link]
    deg_37 = len(sat_37_links)

    print(f"\nSatellite 37 degree after being dragged at t=500: {deg_37} ISLs (links: {sat_37_links})")
    assert deg_37 >= 1, f"Satellite 37 has no ISLs ({deg_37})"


def test_4_timing():
    """4. Timing: the average of 100 calls to build_topology (120 sats, 10 stations) is under 10 ms (print the number)."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)
    pos = positions_ecef(constellation, 0.0)

    # Warmup
    _ = build_topology(pos, ground, prev=None)

    n_calls = 100
    t_start = time.perf_counter()
    prev = None
    for _ in range(n_calls):
        prev = build_topology(pos, ground, prev=prev)
    t_end = time.perf_counter()

    avg_ms = ((t_end - t_start) / n_calls) * 1000.0
    print(f"\nAverage build_topology time over {n_calls} calls: {avg_ms:.3f} ms")
    assert avg_ms < 10.0, f"Average execution time {avg_ms:.3f} ms exceeds 10 ms limit"


def test_5_average_isl_and_degree():
    """5. Print the average ISL count and the average degree at t=0."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)
    pos = positions_ecef(constellation, 0.0)

    topo = build_topology(pos, ground, prev=None)

    isl_count = len(topo.isl)
    n_sats = len(pos)
    avg_degree = (2.0 * isl_count) / n_sats

    print(f"\nConstellation at t=0:")
    print(f"  Total ISL count: {isl_count}")
    print(f"  Average satellite degree: {avg_degree:.2f}")

    assert isl_count > 0
    assert avg_degree > 0.0
