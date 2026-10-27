"""Unit tests for topology foundation module backend/app/sim/topology.py."""

import numpy as np
import pytest

from app.sim.constants import R_EARTH
from app.sim.orbit import latlon_to_ecef, positions_ecef, walker_delta
from app.sim.topology import (
    GroundStation,
    TopoParams,
    Topology,
    default_ground_stations,
    elevation_deg,
    los_clear,
    los_matrix,
)


def test_1_los_clear_basic():
    """1. Two sats on opposite sides of Earth: los_clear is False.

    Two adjacent sats in the same plane (indices 0 and 1 of walker_delta(120,12,1,53,550) at t=0): True.
    """
    # Two sats on opposite sides of Earth
    p_side1 = np.array([6921.0, 0.0, 0.0])
    p_side2 = np.array([-6921.0, 0.0, 0.0])
    assert los_clear(p_side1, p_side2) is False

    # Two adjacent sats in the same plane at t=0
    constellation = walker_delta(120, 12, 1, 53, 550)
    pos = positions_ecef(constellation, 0.0)
    assert los_clear(pos[0], pos[1]) is True


def test_2_los_matrix_agrees_with_los_clear():
    """2. los_matrix agrees with los_clear on 200 random pairs of sats at t=0."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    pos = positions_ecef(constellation, 0.0)
    matrix = los_matrix(pos)

    assert matrix.shape == (120, 120)

    rng = np.random.default_rng(seed=42)
    for _ in range(200):
        i = int(rng.integers(0, 120))
        j = int(rng.integers(0, 120))
        expected = los_clear(pos[i], pos[j])
        assert matrix[i, j] == expected, f"Mismatch at ({i}, {j}): matrix={matrix[i, j]}, scalar={expected}"


def test_3_elevation_deg():
    """3. elevation_deg: a sat directly above a station (same lat/lon, 550 km up, built with latlon_to_ecef)

    gives 90 deg within 1e-6; a sat at the same radius with latitude 8 deg further north
    gives about 26.6 deg (within 0.1); 10 deg further gives about 20.3 deg (within 0.1);
    a sat on the far side of Earth gives a negative elevation.
    """
    st_lat, st_lon = 10.0, 20.0
    ground_ecef = latlon_to_ecef(st_lat, st_lon, 0.0)

    # 1. Directly above station: 90 deg within 1e-6
    sat_above = latlon_to_ecef(st_lat, st_lon, 550.0)
    el_above = elevation_deg(ground_ecef, sat_above)
    assert abs(el_above - 90.0) < 1e-6

    # 2. Same radius, latitude 8 deg further north: ~26.6 deg (within 0.1)
    sat_8deg = latlon_to_ecef(st_lat + 8.0, st_lon, 550.0)
    el_8deg = elevation_deg(ground_ecef, sat_8deg)
    assert abs(el_8deg - 26.6) < 0.1

    # 3. Same radius, latitude 10 deg further north: ~20.3 deg (within 0.1)
    sat_10deg = latlon_to_ecef(st_lat + 10.0, st_lon, 550.0)
    el_10deg = elevation_deg(ground_ecef, sat_10deg)
    assert abs(el_10deg - 20.3) < 0.1

    # 4. Sat on the far side of Earth: negative elevation
    sat_far = latlon_to_ecef(-st_lat, st_lon + 180.0, 550.0)
    el_far = elevation_deg(ground_ecef, sat_far)
    assert el_far < 0.0

    # Also verify vectorized behavior
    sats = np.stack([sat_above, sat_8deg, sat_10deg, sat_far], axis=0)
    els_vec = elevation_deg(ground_ecef, sats)
    assert isinstance(els_vec, np.ndarray)
    assert els_vec.shape == (4,)
    assert abs(els_vec[0] - 90.0) < 1e-6
    assert abs(els_vec[1] - 26.6) < 0.1
    assert abs(els_vec[2] - 20.3) < 0.1
    assert els_vec[3] < 0.0


def test_4_default_ground_stations():
    """4. default_ground_stations returns 10 stations, ids 120..129, ECEF radius 6371 km."""
    stations = default_ground_stations(n_sats=120)

    assert len(stations) == 10
    expected_ids = list(range(120, 130))
    assert [st.id for st in stations] == expected_ids

    expected_names = [
        "Delhi",
        "London",
        "New York",
        "Sao Paulo",
        "Johannesburg",
        "Tokyo",
        "Sydney",
        "Singapore",
        "Dubai",
        "Los Angeles",
    ]
    assert [st.name for st in stations] == expected_names

    for st in stations:
        radius = np.linalg.norm(st.ecef)
        assert np.isclose(radius, R_EARTH, atol=1e-6)
