"""Unit tests for GSL topology construction in backend/app/sim/topology.py."""

import time
import numpy as np
import pytest

from app.sim.constants import GSL_DROP_MARGIN_DEG, GSL_EL_MIN_DEG, GSL_MAX_PER_STATION
from app.sim.orbit import positions_ecef, walker_delta
from app.sim.topology import (
    TopoParams,
    build_gsl,
    build_topology,
    default_ground_stations,
    elevation_deg,
)


def test_1_gsl_elevation_constraint():
    """1. Every GSL has elevation >= params.el_min_deg - params.gsl_drop_margin_deg."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)
    pos = positions_ecef(constellation, 0.0)
    params = TopoParams()

    topo = build_topology(pos, ground, prev=None, params=params)

    assert len(topo.gsl) > 0, "GSL links should not be empty"

    station_map = {gs.id: gs.ecef for gs in ground}
    min_allowed_el = params.el_min_deg - params.gsl_drop_margin_deg

    for sat_id, st_id in topo.gsl:
        st_ecef = station_map[st_id]
        el = elevation_deg(st_ecef, pos[sat_id])
        assert el >= min_allowed_el - 1e-6, (
            f"GSL link ({sat_id}, {st_id}) elevation {el:.2f} deg is below {min_allowed_el} deg"
        )
        # Check slant range exists in dist
        key = (sat_id, st_id) if sat_id < st_id else (st_id, sat_id)
        assert key in topo.dist, f"Key {key} missing from topo.dist"


def test_2_station_gsl_count_and_no_duplicates():
    """2. Each station has at most 3 GSLs; no duplicates."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)
    pos = positions_ecef(constellation, 0.0)
    params = TopoParams()

    topo = build_topology(pos, ground, prev=None, params=params)

    # No duplicates in GSL links
    assert len(topo.gsl) == len(set(topo.gsl)), "Duplicate GSL links found"

    station_counts = {}
    for sat_id, st_id in topo.gsl:
        station_counts[st_id] = station_counts.get(st_id, 0) + 1

    for st in ground:
        count = station_counts.get(st.id, 0)
        assert count <= params.gsl_max_per_station, (
            f"Station {st.name} ({st.id}) has {count} GSLs, exceeding max {params.gsl_max_per_station}"
        )


def test_3_gsl_hysteresis():
    """3. Hysteresis: build at t=0, then at t=2 with prev; at least 95% of the t=0 GSLs are still present (print the percentage)."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)

    pos_t0 = positions_ecef(constellation, 0.0)
    topo_t0 = build_topology(pos_t0, ground, prev=None)

    pos_t2 = positions_ecef(constellation, 2.0)
    topo_t2 = build_topology(pos_t2, ground, prev=topo_t0)

    links_t0 = set(topo_t0.gsl)
    links_t2 = set(topo_t2.gsl)

    retained = links_t0.intersection(links_t2)
    percentage = (len(retained) / len(links_t0)) * 100.0 if links_t0 else 100.0

    print(f"\nGSL hysteresis retention from t=0 to t=2: {percentage:.2f}% ({len(retained)}/{len(links_t0)} GSLs retained)")
    assert percentage >= 95.0, f"GSL retention {percentage:.2f}% is below 95%"


def test_4_full_topology_timing():
    """4. Timing: the average of 100 full build_topology calls (ISL + GSL, 120 sats, 10 stations) is under 10 ms (print the number)."""
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
    print(f"\nAverage full build_topology (ISL + GSL) time over {n_calls} calls: {avg_ms:.3f} ms")
    assert avg_ms < 10.0, f"Average execution time {avg_ms:.3f} ms exceeds 10 ms limit"


def test_5_gsl_station_counts_info():
    """5. Print how many GSLs each station has at t=0 (information only, no assertion)."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)
    pos = positions_ecef(constellation, 0.0)

    topo = build_topology(pos, ground, prev=None)

    station_counts = {}
    for sat_id, st_id in topo.gsl:
        station_counts[st_id] = station_counts.get(st_id, 0) + 1

    print(f"\nGround station GSL connections at t=0:")
    print(f"{'Station ID':<12} | {'Name':<15} | {'GSL Count':<10}")
    print("-" * 42)
    for st in ground:
        count = station_counts.get(st.id, 0)
        print(f"{st.id:<12} | {st.name:<15} | {count:<10}")
