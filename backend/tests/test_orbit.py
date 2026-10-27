"""Unit tests for orbital mechanics simulation module backend/app/sim/orbit.py."""

import numpy as np
import pytest

from app.sim.constants import MU, OMEGA_E, R_EARTH
from app.sim.orbit import (
    Constellation,
    ecef_to_latlon,
    ground_track,
    latlon_to_ecef,
    positions_ecef,
    propagate_eci,
    rephase_to,
    walker_delta,
)


def test_1_walker_delta_geometry():
    """1. walker_delta(120, 12, 1, 53, 550) gives 120 sats, 12 planes x 10, all radius 6921 km at any t."""
    constellation = walker_delta(120, 12, 1, 53, 550)

    # 120 satellites total
    assert len(constellation) == 120
    assert constellation.num_sats == 120

    # 12 planes with 10 satellites each
    unique_planes, counts = np.unique(constellation.plane_index, return_counts=True)
    assert len(unique_planes) == 12
    assert np.all(counts == 10)

    # Check radius 6921 km at any t (e.g. t = 0, 100, 1000, 5000 s)
    expected_radius = 6371.0 + 550.0  # 6921 km
    for t in [0.0, 100.0, 1000.0, 5000.0]:
        r_eci = propagate_eci(constellation, t)
        r_ecef = positions_ecef(constellation, t)

        radii_eci = np.linalg.norm(r_eci, axis=-1)
        radii_ecef = np.linalg.norm(r_ecef, axis=-1)

        np.testing.assert_allclose(radii_eci, expected_radius, atol=1e-6)
        np.testing.assert_allclose(radii_ecef, expected_radius, atol=1e-6)


def test_2_orbital_period():
    """2. Period: position at t=0 and t=2*pi/n is identical (ECI) within 1e-6 km. Period is between 5700 and 5760 s."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    period = 2.0 * np.pi / constellation.n[0]

    # Period is between 5700 and 5760 s
    assert 5700.0 <= period <= 5760.0

    # ECI position at t=0 and t=period is identical within 1e-6 km
    r_t0 = propagate_eci(constellation, 0.0)
    r_tp = propagate_eci(constellation, period)
    diff = np.linalg.norm(r_tp - r_t0, axis=-1)

    assert np.max(diff) < 1e-6


def test_3_orbital_speed():
    """3. Speed from a 1 s finite difference (ECI) is between 7.5 and 7.7 km/s."""
    constellation = walker_delta(120, 12, 1, 53, 550)

    r_t0 = propagate_eci(constellation, 0.0)
    r_t1 = propagate_eci(constellation, 1.0)
    speeds = np.linalg.norm(r_t1 - r_t0, axis=-1)  # km/s over 1 s interval

    assert np.all(speeds >= 7.5)
    assert np.all(speeds <= 7.7)


def test_4_max_latitude():
    """4. Max |latitude| over a full orbit for any sat is <= 53.001 deg."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    period = 2.0 * np.pi / constellation.n[0]

    # Sample across a full orbital period
    t_samples = np.linspace(0.0, period, 180)
    for sat_idx in [0, 5, 23, 59, 119]:
        track = ground_track(constellation, sat_idx, 0.0, period, period / 180.0)
        lats = [abs(lat) for lat, _ in track]
        assert max(lats) <= 53.001

    # Also test vectorized across all satellites at multiple phases
    for t in t_samples[:10]:
        pos_ecef = positions_ecef(constellation, t)
        lats, _, _ = ecef_to_latlon(pos_ecef)
        assert np.max(np.abs(lats)) <= 53.001


def test_5_longitude_drift():
    """5. After one orbital period, ECEF longitude of a sat has drifted by about -(OMEGA_E*period) rad (about -23.9 deg), within 0.1 deg."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    period = 2.0 * np.pi / constellation.n[0]

    pos_0 = positions_ecef(constellation, 0.0)
    pos_T = positions_ecef(constellation, period)

    _, lon_0, _ = ecef_to_latlon(pos_0)
    _, lon_T, _ = ecef_to_latlon(pos_T)

    # Angular difference with wrapping into [-180, 180]
    drift = (lon_T - lon_0 + 180.0) % 360.0 - 180.0
    expected_drift_deg = np.degrees(-OMEGA_E * period)

    # Drift should be about -23.9 deg within 0.1 deg
    assert np.isclose(expected_drift_deg, -23.94, atol=0.1)
    np.testing.assert_allclose(drift, expected_drift_deg, atol=0.1)


def test_6_minimum_pairwise_distance():
    """6. Minimum pairwise distance between all 120 sats at t=0 and t=1000 is > 100 km."""
    constellation = walker_delta(120, 12, 1, 53, 550)

    # Note: Adjacent orbital planes converge near the +/-53 deg latitude turning points,
    # so about 224 km at t=0 and about 203 km at t=1000 is the real physical minimum separation
    # for the Walker 120/12/1 constellation.
    for t in [0.0, 1000.0]:
        pos = positions_ecef(constellation, t)
        # Compute all pairwise euclidean distances
        diff = pos[:, np.newaxis, :] - pos[np.newaxis, :, :]
        dist_matrix = np.linalg.norm(diff, axis=-1)
        np.fill_diagonal(dist_matrix, np.inf)
        min_dist = np.min(dist_matrix)
        assert min_dist > 100.0, f"Min distance at t={t} was {min_dist} km <= 100 km"


def test_7_rephase_to_random_cases():
    """7. rephase_to: for 50 random cases (lat in [-52,52], lon in [-180,180], t in [0,6000], random sat),

    afterwards the sat's lat/lon at t equals the target within 0.01 deg,
    radius is unchanged, and the sign of dz/dt is the same as before.
    """
    rng = np.random.default_rng(seed=42)

    for _ in range(50):
        constellation = walker_delta(120, 12, 1, 53, 550)
        sat_idx = int(rng.integers(0, 120))
        target_lat = float(rng.uniform(-52.0, 52.0))
        target_lon = float(rng.uniform(-180.0, 180.0))
        target_t = float(rng.uniform(0.0, 6000.0))

        # Check dz/dt sign before rephase
        dt = 1e-4
        pos_before_t = positions_ecef(constellation, target_t)[sat_idx]
        pos_before_tdt = positions_ecef(constellation, target_t + dt)[sat_idx]
        dz_dt_before = (pos_before_tdt[2] - pos_before_t[2]) / dt
        expected_north = dz_dt_before >= 0.0

        # Perform rephase
        returned_c = rephase_to(constellation, sat_idx, target_lat, target_lon, target_t)
        assert returned_c is constellation

        # Check position at t
        pos_after_t = positions_ecef(constellation, target_t)[sat_idx]
        pos_after_tdt = positions_ecef(constellation, target_t + dt)[sat_idx]
        dz_dt_after = (pos_after_tdt[2] - pos_after_t[2]) / dt

        lat_res, lon_res, alt_res = ecef_to_latlon(pos_after_t)

        # Target latitude matched within 0.01 deg
        assert abs(lat_res - target_lat) < 0.01

        # Target longitude matched within 0.01 deg (accounting for wrapping)
        lon_diff = (lon_res - target_lon + 180.0) % 360.0 - 180.0
        assert abs(lon_diff) < 0.01

        # Radius unchanged
        radius = np.linalg.norm(pos_after_t)
        assert abs(radius - 6921.0) < 1e-5

        # Sign of dz/dt matches before (ignoring tiny numerical zeros at inflection points)
        if abs(dz_dt_before) > 1e-6:
            assert (dz_dt_after >= 0.0) == expected_north


def test_8_rephase_to_exceeding_latitude():
    """8. rephase_to with |lat| = 60 raises inclination to 60 deg and still lands on the target."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    sat_idx = 7
    target_lat = 60.0
    target_lon = -45.0
    target_t = 1500.0

    rephase_to(constellation, sat_idx, target_lat, target_lon, target_t)

    # Inclination raised to 60 deg
    inc_deg = np.degrees(constellation.inc[sat_idx])
    assert np.isclose(inc_deg, 60.0, atol=1e-5)

    # Satellite lands on target
    pos_t = positions_ecef(constellation, target_t)[sat_idx]
    lat_res, lon_res, alt_res = ecef_to_latlon(pos_t)

    assert abs(lat_res - target_lat) < 0.01
    lon_diff = (lon_res - target_lon + 180.0) % 360.0 - 180.0
    assert abs(lon_diff) < 0.01
    assert abs(np.linalg.norm(pos_t) - 6921.0) < 1e-5


def test_9_latlon_to_ecef_roundtrip():
    """9. latlon_to_ecef -> ecef_to_latlon round-trip within 1e-9."""
    # Test scalar round-trip
    lat_in, lon_in, alt_in = 34.0522, -118.2437, 550.0
    ecef = latlon_to_ecef(lat_in, lon_in, alt_in)
    lat_out, lon_out, alt_out = ecef_to_latlon(ecef)

    assert abs(lat_out - lat_in) < 1e-9
    assert abs(lon_out - lon_in) < 1e-9
    assert abs(alt_out - alt_in) < 1e-9

    # Test vectorized round-trip
    lats = np.array([-89.0, -45.0, -10.0, 0.0, 15.0, 53.0, 89.0])
    lons = np.array([-180.0, -120.0, -45.0, 0.0, 45.0, 120.0, 180.0])
    alts = np.array([0.0, 100.0, 500.0, 550.0, 600.0, 1000.0, 35786.0])

    ecef_arr = latlon_to_ecef(lats, lons, alts)
    lat_arr_out, lon_arr_out, alt_arr_out = ecef_to_latlon(ecef_arr)

    np.testing.assert_allclose(lat_arr_out, lats, atol=1e-9)
    # Handle lon +/- 180 boundary
    lon_diff = (lon_arr_out - lons + 180.0) % 360.0 - 180.0
    np.testing.assert_allclose(lon_diff, 0.0, atol=1e-9)
    np.testing.assert_allclose(alt_arr_out, alts, atol=1e-9)


def test_ground_track():
    """Verify ground_track returns list of (lat, lon) coordinates."""
    constellation = walker_delta(120, 12, 1, 53, 550)
    track = ground_track(constellation, sat_index=0, t0=0.0, t1=600.0, step=60.0)

    assert isinstance(track, list)
    assert len(track) == 11  # 0, 60, ..., 600
    for lat, lon in track:
        assert -53.001 <= lat <= 53.001
        assert -180.0 <= lon <= 180.0
