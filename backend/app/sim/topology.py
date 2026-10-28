"""Topology foundations for satellite constellation networking.

Defines GroundStation, TopoParams, Topology dataclasses, default ground stations,
geometric line-of-sight checking, and local elevation angle calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Union

import numpy as np

from app.sim.constants import (
    ATMOS_KM,
    GSL_DROP_MARGIN_DEG,
    GSL_EL_MIN_DEG,
    GSL_MAX_PER_STATION,
    ISL_BUILD_FRAC,
    ISL_MAX_DEGREE,
    ISL_MAX_RANGE_KM,
    R_EARTH,
)
from app.sim.orbit import latlon_to_ecef


@dataclass
class GroundStation:
    """Ground station location and coordinates."""

    id: int
    name: str
    lat: float
    lon: float
    ecef: np.ndarray


@dataclass
class TopoParams:
    """Parameters governing constellation network topology and link budgets."""

    isl_max_range_km: float = ISL_MAX_RANGE_KM
    max_deg: int = ISL_MAX_DEGREE
    isl_build_frac: float = ISL_BUILD_FRAC
    atmos_km: float = ATMOS_KM
    el_min_deg: float = GSL_EL_MIN_DEG
    gsl_drop_margin_deg: float = GSL_DROP_MARGIN_DEG
    gsl_max_per_station: int = GSL_MAX_PER_STATION


@dataclass
class Topology:
    """Network topology graph snapshot at a specific point in time.

    All link keys in isl and gsl are normalised as (min, max).
    GSL tuples are (sat_id, station_id); since station_id >= n_sats,
    they are inherently normalised.
    """

    isl: List[Tuple[int, int]]
    gsl: List[Tuple[int, int]]
    pos: np.ndarray  # Shape: (N, 3), satellite ECEF coordinates
    ground_pos: np.ndarray  # Shape: (G, 3), ground station ECEF coordinates
    dist: Dict[Tuple[int, int], float] = field(default_factory=dict)


def default_ground_stations(n_sats: int = 120) -> List[GroundStation]:
    """Return default ground stations with IDs starting from n_sats.

    NOTE: These 10 ground stations are PLACEHOLDERS to be replaced later with
    production station datasets or configurable locations.
    """
    raw_stations = [
        ("Delhi", 28.61, 77.21),
        ("London", 51.51, -0.13),
        ("New York", 40.71, -74.01),
        ("Sao Paulo", -23.55, -46.63),
        ("Johannesburg", -26.20, 28.05),
        ("Tokyo", 35.68, 139.69),
        ("Sydney", -33.87, 151.21),
        ("Singapore", 1.35, 103.82),
        ("Dubai", 25.20, 55.27),
        ("Los Angeles", 34.05, -118.24),
    ]

    stations: List[GroundStation] = []
    for idx, (name, lat, lon) in enumerate(raw_stations):
        st_id = n_sats + idx
        ecef = latlon_to_ecef(lat, lon, 0.0)
        stations.append(
            GroundStation(
                id=st_id,
                name=name,
                lat=lat,
                lon=lon,
                ecef=ecef,
            )
        )
    return stations


def los_clear(
    p1: np.ndarray,
    p2: np.ndarray,
    atmos_km: float = ATMOS_KM,
) -> bool:
    """Check if straight line-of-sight segment p1-p2 clears Earth and atmosphere.

    Finds the closest point on the segment p1-p2 to Earth's centre (origin)
    and verifies that its distance is at least R_EARTH + atmos_km.

    Args:
        p1: (3,) position vector of first point in km.
        p2: (3,) position vector of second point in km.
        atmos_km: Earth atmospheric occlusion height in km.

    Returns:
        True if the line of sight is clear, False if occluded.
    """
    p1_arr = np.asarray(p1, dtype=np.float64)
    p2_arr = np.asarray(p2, dtype=np.float64)

    d = p2_arr - p1_arr
    d_sq = np.sum(d**2)

    if d_sq < 1e-12:
        closest_point = p1_arr
    else:
        # Unconstrained parameter u minimizing |p1 + u * d|^2
        u = -np.dot(p1_arr, d) / d_sq
        u_clamped = max(0.0, min(1.0, float(u)))
        closest_point = p1_arr + u_clamped * d

    min_dist_sq = np.sum(closest_point**2)
    min_allowed_dist = R_EARTH + atmos_km
    return bool(min_dist_sq >= min_allowed_dist * min_allowed_dist)


def los_matrix(
    pos: np.ndarray,
    atmos_km: float = ATMOS_KM,
) -> np.ndarray:
    """Vectorised pairwise line-of-sight matrix computation.

    Args:
        pos: (N, 3) array of satellite ECEF/ECI position coordinates in km.
        atmos_km: Atmospheric occlusion height in km.

    Returns:
        (N, N) boolean array where element [i, j] is True if straight LOS clears.
    """
    pos_arr = np.asarray(pos, dtype=np.float64)
    # Broadcast to pairwise combinations: p1 is (N, 1, 3), p2 is (1, N, 3)
    p1 = pos_arr[:, np.newaxis, :]
    p2 = pos_arr[np.newaxis, :, :]

    d = p2 - p1  # (N, N, 3)
    d_sq = np.sum(d**2, axis=-1)  # (N, N)

    # Dot product p1 . d: (N, N)
    p1_dot_d = np.sum(p1 * d, axis=-1)

    # Parameter u clamped to [0, 1]
    safe_d_sq = np.where(d_sq > 1e-12, d_sq, 1.0)
    u = np.where(d_sq > 1e-12, -p1_dot_d / safe_d_sq, 0.0)
    u_clamped = np.clip(u, 0.0, 1.0)  # (N, N)

    # Closest point on each segment: (N, N, 3)
    closest_pts = p1 + u_clamped[..., np.newaxis] * d
    min_dist_sq = np.sum(closest_pts**2, axis=-1)  # (N, N)

    min_allowed = R_EARTH + atmos_km
    return min_dist_sq >= (min_allowed * min_allowed)


def elevation_deg(
    ground_ecef: np.ndarray,
    sat_ecef: np.ndarray,
) -> Union[float, np.ndarray]:
    """Compute elevation angle of satellite above local ground horizon in degrees.

    Uses spherical Earth local normal:
        sin(el) = dot(sat - ground, ground_unit) / |sat - ground|

    Args:
        ground_ecef: (3,) or (..., 3) array of ground station ECEF coordinates.
        sat_ecef: (3,) or (..., 3) array of satellite ECEF coordinates.

    Returns:
        Elevation angle in degrees (float if scalar inputs, ndarray if array inputs).
    """
    g = np.asarray(ground_ecef, dtype=np.float64)
    s = np.asarray(sat_ecef, dtype=np.float64)

    # Relative line-of-sight vector from ground station to satellite
    rho = s - g
    rho_norm = np.linalg.norm(rho, axis=-1)

    # Local zenith / normal unit vector for spherical Earth
    g_norm = np.linalg.norm(g, axis=-1, keepdims=True)
    safe_g_norm = np.where(g_norm > 0.0, g_norm, 1.0)
    ground_unit = g / safe_g_norm

    # Dot product along coordinate axis
    dot = np.sum(rho * ground_unit, axis=-1)
    safe_rho_norm = np.where(rho_norm > 0.0, rho_norm, 1.0)

    sin_el = np.clip(dot / safe_rho_norm, -1.0, 1.0)
    el_deg = np.degrees(np.arcsin(sin_el))

    if g.ndim == 1 and s.ndim == 1:
        return float(el_deg)
    return el_deg


def build_isl(
    pos: np.ndarray,
    prev_isl: Optional[List[Tuple[int, int]]] = None,
    params: Optional[TopoParams] = None,
) -> List[Tuple[int, int]]:
    """Build inter-satellite links (ISLs) using distance, LOS clearing, and hysteresis.

    Args:
        pos: (N, 3) array of satellite positions in ECEF/ECI coordinates (km).
        prev_isl: Previous topology ISL list of (i, j) pairs, or None.
        params: TopoParams instance (defaults to standard parameters if None).

    Returns:
        List of (i, j) tuples with i < j, without duplicates, respecting max_deg.
    """
    if params is None:
        params = TopoParams()

    n_sats = len(pos)
    if n_sats <= 1:
        return []

    # Compute full distance matrix and line-of-sight matrix with NumPy
    diff = pos[:, np.newaxis, :] - pos[np.newaxis, :, :]
    d_sq = np.sum(diff**2, axis=-1)
    dist_matrix = np.sqrt(d_sq)

    los = los_matrix(pos, params.atmos_km)

    degrees = np.zeros(n_sats, dtype=np.int32)
    isl_links: List[Tuple[int, int]] = []
    kept_set: set[Tuple[int, int]] = set()
    max_total_links = n_sats * params.max_deg // 2

    # STEP A (hysteresis):
    # Keep previous links that are still candidates (LOS clear, dist <= isl_max_range_km),
    # sorted by distance ascending, if both endpoints have fewer than max_deg links.
    if prev_isl:
        prev_candidates = []
        seen_prev = set()
        for u, v in prev_isl:
            i, j = (u, v) if u < v else (v, u)
            if i == j or (i, j) in seen_prev:
                continue
            seen_prev.add((i, j))
            if 0 <= i < n_sats and 0 <= j < n_sats:
                d = dist_matrix[i, j]
                if d <= params.isl_max_range_km and los[i, j]:
                    prev_candidates.append((d, i, j))

        prev_candidates.sort(key=lambda item: item[0])

        for _, i, j in prev_candidates:
            if degrees[i] < params.max_deg and degrees[j] < params.max_deg:
                degrees[i] += 1
                degrees[j] += 1
                isl_links.append((i, j))
                kept_set.add((i, j))
                if len(isl_links) >= max_total_links:
                    break

    # STEP B:
    # Add new links whose distance <= isl_build_frac * isl_max_range_km,
    # sorted by distance ascending, if both endpoints are still below max_deg.
    if len(isl_links) < max_total_links:
        triu_i, triu_j = np.triu_indices(n_sats, k=1)
        triu_dists = dist_matrix[triu_i, triu_j]
        triu_los = los[triu_i, triu_j]

        build_range = params.isl_build_frac * params.isl_max_range_km
        valid_mask = triu_los & (triu_dists <= build_range)

        cand_i = triu_i[valid_mask]
        cand_j = triu_j[valid_mask]
        cand_dists = triu_dists[valid_mask]

        sort_order = np.argsort(cand_dists)
        sorted_i = cand_i[sort_order]
        sorted_j = cand_j[sort_order]

        for i_raw, j_raw in zip(sorted_i, sorted_j):
            pair = (int(i_raw), int(j_raw))
            if pair in kept_set:
                continue
            if degrees[pair[0]] < params.max_deg and degrees[pair[1]] < params.max_deg:
                degrees[pair[0]] += 1
                degrees[pair[1]] += 1
                isl_links.append(pair)
                kept_set.add(pair)
                if len(isl_links) >= max_total_links:
                    break

    return isl_links


def build_gsl(
    sat_pos: np.ndarray,
    ground: List[GroundStation],
    prev_gsl: Optional[List[Tuple[int, int]]] = None,
    params: Optional[TopoParams] = None,
) -> List[Tuple[int, int]]:
    """Build ground-satellite links (GSLs) using local elevation and hysteresis.

    Args:
        sat_pos: (N, 3) array of satellite ECEF coordinates in km.
        ground: List of GroundStation objects.
        prev_gsl: Previous topology GSL list of (sat_id, station_id) pairs, or None.
        params: TopoParams instance (defaults to standard parameters if None).

    Returns:
        List of (sat_id, station_id) tuples.
    """
    if params is None:
        params = TopoParams()

    if not ground or len(sat_pos) == 0:
        return []

    n_sats = len(sat_pos)
    ground_pos = np.stack([gs.ecef for gs in ground], axis=0)  # (G, 3)

    # Vectorised elevation calculation for all ground stations to all satellites
    # ground_pos[:, None, :] is (G, 1, 3); sat_pos[None, :, :] is (1, N, 3)
    # Result is (G, N) array of elevations in degrees
    el_matrix = elevation_deg(
        ground_pos[:, np.newaxis, :],
        sat_pos[np.newaxis, :, :],
    )

    drop_threshold = params.el_min_deg - params.gsl_drop_margin_deg
    build_threshold = params.el_min_deg
    max_per_station = params.gsl_max_per_station

    # Index previous links by station_id
    prev_by_station: Dict[int, List[int]] = {}
    if prev_gsl:
        for sat_id, st_id in prev_gsl:
            if 0 <= sat_id < n_sats:
                prev_by_station.setdefault(st_id, []).append(sat_id)

    gsl_links: List[Tuple[int, int]] = []

    for g_idx, st in enumerate(ground):
        elevations = el_matrix[g_idx]
        station_sats: List[int] = []
        assigned_sats: set[int] = set()

        # STEP A (hysteresis):
        # Keep previous links of this station whose elevation is still >= el_min_deg - gsl_drop_margin_deg
        # (keep the best ones first, up to gsl_max_per_station).
        prev_sats = prev_by_station.get(st.id, [])
        if prev_sats:
            prev_candidates = []
            seen_prev_sat = set()
            for s_id in prev_sats:
                if s_id not in seen_prev_sat:
                    seen_prev_sat.add(s_id)
                    el = elevations[s_id]
                    if el >= drop_threshold:
                        prev_candidates.append((el, s_id))

            # Sort descending by elevation
            prev_candidates.sort(key=lambda x: x[0], reverse=True)

            for _, s_id in prev_candidates[:max_per_station]:
                station_sats.append(s_id)
                assigned_sats.add(s_id)

        # STEP B:
        # If the station has fewer than gsl_max_per_station links,
        # add the satellites with the highest elevation that have elevation >= el_min_deg,
        # until the limit is reached.
        needed = max_per_station - len(station_sats)
        if needed > 0:
            valid_new_mask = elevations >= build_threshold
            cand_sats = np.where(valid_new_mask)[0]

            if len(cand_sats) > 0:
                filtered_cands = [s for s in cand_sats if s not in assigned_sats]
                if filtered_cands:
                    cand_elevations = elevations[filtered_cands]
                    sort_order = np.argsort(cand_elevations)[::-1]  # Descending
                    for idx in sort_order[:needed]:
                        s_id = int(filtered_cands[idx])
                        station_sats.append(s_id)
                        assigned_sats.add(s_id)

        for s_id in station_sats:
            gsl_links.append((s_id, st.id))

    return gsl_links


def build_topology(
    sat_pos: np.ndarray,
    ground: List[GroundStation],
    prev: Optional[Topology] = None,
    params: Optional[TopoParams] = None,
) -> Topology:
    """Build constellation network topology at a single time step.

    Calls build_isl with prev.isl (or [] if prev is None), calls build_gsl
    with prev.gsl (or [] if prev is None), fills pos, ground_pos from the
    ground station list, and computes dist for every ISL and GSL in km.

    Args:
        sat_pos: (N, 3) array of satellite ECEF coordinates in km.
        ground: List of GroundStation objects.
        prev: Previous Topology snapshot (optional).
        params: TopoParams configuration (optional).

    Returns:
        Topology snapshot dataclass instance.
    """
    if params is None:
        params = TopoParams()

    prev_isl = prev.isl if prev is not None and prev.isl is not None else []
    prev_gsl = prev.gsl if prev is not None and prev.gsl is not None else []

    isl = build_isl(sat_pos, prev_isl=prev_isl, params=params)
    gsl = build_gsl(sat_pos, ground=ground, prev_gsl=prev_gsl, params=params)

    if ground:
        ground_pos = np.stack([gs.ecef for gs in ground], axis=0)
        station_map = {gs.id: gs.ecef for gs in ground}
    else:
        ground_pos = np.empty((0, 3), dtype=np.float64)
        station_map = {}

    # Compute Euclidean distance for every ISL link
    dist: Dict[Tuple[int, int], float] = {}
    for i, j in isl:
        d = float(np.linalg.norm(sat_pos[i] - sat_pos[j]))
        dist[(i, j)] = d

    # Add each GSL's slant range (km) using its normalised key
    for sat_id, st_id in gsl:
        st_ecef = station_map[st_id]
        d = float(np.linalg.norm(sat_pos[sat_id] - st_ecef))
        key = (sat_id, st_id) if sat_id < st_id else (st_id, sat_id)
        dist[key] = d

    return Topology(
        isl=isl,
        gsl=gsl,
        pos=sat_pos,
        ground_pos=ground_pos,
        dist=dist,
    )

