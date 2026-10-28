"""Orbital mechanics and constellation simulation.

This module provides circular orbit kinematics, Walker Delta constellation
generation, coordinate transformations (ECI, ECEF, Lat/Lon), satellite rephasing,
and ground track generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union

import numpy as np

from app.sim.constants import MU, OMEGA_E, R_EARTH


@dataclass
class Constellation:
    """Satellite constellation state storing per-satellite orbital parameters.

    Attributes:
        a: Semi-major axis / orbit radius in km (shape: (N,))
        inc: Inclination in radians (shape: (N,))
        raan: Right Ascension of Ascending Node in radians (shape: (N,))
        u0: Initial true anomaly / argument of latitude at t=0 in radians (shape: (N,))
        n: Mean motion in rad/s (shape: (N,))
        plane_index: Integer index of orbital plane for each satellite (shape: (N,))
    """

    a: np.ndarray
    inc: np.ndarray
    raan: np.ndarray
    u0: np.ndarray
    n: np.ndarray
    plane_index: np.ndarray

    def __init__(
        self,
        a: Union[np.ndarray, List[float]],
        inc: Union[np.ndarray, List[float]],
        raan: Union[np.ndarray, List[float]],
        u0: Union[np.ndarray, List[float]],
        n: Union[np.ndarray, List[float]],
        plane_index: Optional[Union[np.ndarray, List[int]]] = None,
        plane: Optional[Union[np.ndarray, List[int]]] = None,
    ):
        self.a = np.asarray(a, dtype=np.float64)
        self.inc = np.asarray(inc, dtype=np.float64)
        self.raan = np.asarray(raan, dtype=np.float64)
        self.u0 = np.asarray(u0, dtype=np.float64)
        self.n = np.asarray(n, dtype=np.float64)

        target_plane = plane_index if plane_index is not None else plane
        if target_plane is None:
            raise ValueError("Must provide plane_index or plane")
        self.plane_index = np.asarray(target_plane, dtype=np.int64)

    @property
    def plane(self) -> np.ndarray:
        """Alias for plane_index."""
        return self.plane_index

    @plane.setter
    def plane(self, value: Union[np.ndarray, List[int]]) -> None:
        self.plane_index = np.asarray(value, dtype=np.int64)

    @property
    def num_sats(self) -> int:
        """Total number of satellites."""
        return len(self.a)

    def __len__(self) -> int:
        return len(self.a)


def walker_delta(
    num_sats: int,
    num_planes: int,
    f: int,
    inc_deg: float,
    altitude_km: float,
) -> Constellation:
    """Generate a Walker Delta T/P/F satellite constellation.

    Args:
        num_sats: Total number of satellites (T).
        num_planes: Number of orbital planes (P).
        f: Relative phasing parameter (F), integer between 0 and P-1.
        inc_deg: Orbital inclination in degrees.
        altitude_km: Orbital altitude above spherical Earth in km.

    Returns:
        Constellation dataclass instance with initialized arrays.
    """
    if num_sats <= 0:
        raise ValueError("num_sats must be positive")
    if num_planes <= 0:
        raise ValueError("num_planes must be positive")
    if num_sats % num_planes != 0:
        raise ValueError(
            f"num_sats ({num_sats}) must be divisible by num_planes ({num_planes})"
        )

    sats_per_plane = num_sats // num_planes
    orbit_radius = R_EARTH + altitude_km
    mean_motion = np.sqrt(MU / (orbit_radius**3))
    inc_rad = np.radians(inc_deg)

    a = np.full(num_sats, orbit_radius, dtype=np.float64)
    inc = np.full(num_sats, inc_rad, dtype=np.float64)
    raan = np.empty(num_sats, dtype=np.float64)
    u0 = np.empty(num_sats, dtype=np.float64)
    n = np.full(num_sats, mean_motion, dtype=np.float64)
    plane_idx = np.empty(num_sats, dtype=np.int64)

    idx = 0
    for p in range(num_planes):
        raan_deg = 360.0 * p / num_planes
        raan_val = np.radians(raan_deg)
        for j in range(sats_per_plane):
            u0_deg = (
                360.0 * j / sats_per_plane + f * 360.0 * p / num_sats
            ) % 360.0
            raan[idx] = raan_val
            u0[idx] = np.radians(u0_deg)
            plane_idx[idx] = p
            idx += 1

    return Constellation(
        a=a,
        inc=inc,
        raan=raan,
        u0=u0,
        n=n,
        plane_index=plane_idx,
    )


def propagate_eci(constellation: Constellation, t: float) -> np.ndarray:
    """Propagate constellation to time t in Earth-Centered Inertial (ECI) coordinates.

    Position in orbital plane at angle u = u0 + n*t is (a cos u, a sin u, 0).
    Rotated by inclination i about x-axis, then by RAAN about z-axis.

    Args:
        constellation: Satellite constellation.
        t: Propagation time in seconds from epoch.

    Returns:
        (N, 3) ndarray of ECI position vectors in km.
    """
    u = constellation.u0 + constellation.n * t

    cos_u = np.cos(u)
    sin_u = np.sin(u)
    cos_i = np.cos(constellation.inc)
    sin_i = np.sin(constellation.inc)
    cos_raan = np.cos(constellation.raan)
    sin_raan = np.sin(constellation.raan)

    # In plane rotated by inclination i:
    x_prime = constellation.a * cos_u
    y_prime = constellation.a * sin_u * cos_i
    z_prime = constellation.a * sin_u * sin_i

    # Rotated by RAAN about z-axis:
    x_eci = x_prime * cos_raan - y_prime * sin_raan
    y_eci = x_prime * sin_raan + y_prime * cos_raan
    z_eci = z_prime

    return np.column_stack([x_eci, y_eci, z_eci])


def eci_to_ecef(r_eci: np.ndarray, t: float) -> np.ndarray:
    """Rotate ECI coordinates about z-axis by -OMEGA_E * t into ECEF coordinates.

    Args:
        r_eci: (3,) or (..., 3) array of ECI position vectors in km.
        t: Time in seconds.

    Returns:
        ECEF position vectors in km matching input dimensions.
    """
    r_arr = np.asarray(r_eci, dtype=np.float64)
    theta = -OMEGA_E * t

    cos_th = np.cos(theta)
    sin_th = np.sin(theta)

    x = r_arr[..., 0]
    y = r_arr[..., 1]
    z = r_arr[..., 2]

    x_ecef = x * cos_th - y * sin_th
    y_ecef = x * sin_th + y * cos_th
    z_ecef = z

    return np.stack([x_ecef, y_ecef, z_ecef], axis=-1)


def positions_ecef(constellation: Constellation, t: float) -> np.ndarray:
    """Compute Earth-Centered Earth-Fixed (ECEF) coordinates for all satellites at time t.

    Args:
        constellation: Satellite constellation.
        t: Time in seconds.

    Returns:
        (N, 3) ndarray of ECEF coordinates in km.
    """
    r_eci = propagate_eci(constellation, t)
    return eci_to_ecef(r_eci, t)


def ecef_to_latlon(
    *args: Any,
) -> Union[Tuple[float, float, float], Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Convert ECEF coordinates to geodetic latitude, longitude, and altitude on spherical Earth.

    Supports either ecef_to_latlon(r) where r is (3,) or (..., 3),
    or ecef_to_latlon(x, y, z).

    Args:
        *args: Either a single array `r` or three scalars/arrays `(x, y, z)`.

    Returns:
        Tuple of (lat_deg, lon_deg, alt_km).
    """
    if len(args) == 1:
        r_arr = np.asarray(args[0], dtype=np.float64)
        x = r_arr[..., 0]
        y = r_arr[..., 1]
        z = r_arr[..., 2]
        is_scalar = r_arr.ndim == 1 and r_arr.shape[0] == 3
    elif len(args) == 3:
        x = np.asarray(args[0], dtype=np.float64)
        y = np.asarray(args[1], dtype=np.float64)
        z = np.asarray(args[2], dtype=np.float64)
        is_scalar = x.ndim == 0
    else:
        raise ValueError(
            "ecef_to_latlon expects either ecef_to_latlon(r) or ecef_to_latlon(x, y, z)"
        )

    r_mag = np.sqrt(x**2 + y**2 + z**2)
    alt_km = r_mag - R_EARTH

    # Guard against division by zero at center of Earth
    safe_r = np.where(r_mag > 0, r_mag, 1.0)
    sin_lat = np.clip(z / safe_r, -1.0, 1.0)
    lat_deg = np.degrees(np.arcsin(sin_lat))
    lon_deg = np.degrees(np.arctan2(y, x))

    if is_scalar:
        return float(lat_deg), float(lon_deg), float(alt_km)
    return lat_deg, lon_deg, alt_km


def latlon_to_ecef(
    lat_deg: Union[float, np.ndarray, Tuple[float, float, float]],
    lon_deg: Optional[Union[float, np.ndarray]] = None,
    alt_km: Union[float, np.ndarray] = 0.0,
) -> np.ndarray:
    """Convert spherical latitude, longitude, and altitude to ECEF coordinates.

    Supports latlon_to_ecef(lat_deg, lon_deg, alt_km) or latlon_to_ecef((lat, lon, alt)).

    Args:
        lat_deg: Latitude in degrees, or a 3-element tuple/list/array (lat, lon, alt).
        lon_deg: Longitude in degrees (optional if lat_deg is a tuple).
        alt_km: Altitude above Earth's surface in km (default 0.0).

    Returns:
        (3,) or (..., 3) ndarray of ECEF coordinates in km.
    """
    if lon_deg is None:
        coords = np.asarray(lat_deg, dtype=np.float64)
        lat = coords[..., 0]
        lon = coords[..., 1]
        alt = coords[..., 2]
    else:
        lat = np.asarray(lat_deg, dtype=np.float64)
        lon = np.asarray(lon_deg, dtype=np.float64)
        alt = np.asarray(alt_km, dtype=np.float64)

    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    r = R_EARTH + alt

    x = r * np.cos(lat_rad) * np.cos(lon_rad)
    y = r * np.cos(lat_rad) * np.sin(lon_rad)
    z = r * np.sin(lat_rad)

    return np.stack([x, y, z], axis=-1)


def rephase_to(
    constellation: Constellation,
    sat_index: int,
    lat_deg: float,
    lon_deg: float,
    t: float,
) -> Constellation:
    """Rephase a satellite to target lat/lon at time t.

    Updates the satellite's RAAN and u0 (and inclination if |lat| > inclination,
    setting inclination = |lat|) so that at time t its ECEF position matches the
    target lat/lon at the same orbit radius, and its direction of motion (sign of
    dz/dt) is preserved.

    NOTE: This function modifies the constellation in place AND returns the
    updated constellation instance.

    Args:
        constellation: Constellation instance to update.
        sat_index: Index of the satellite to rephase.
        lat_deg: Target latitude in degrees.
        lon_deg: Target longitude in degrees.
        t: Time in seconds at which the target position is reached.

    Returns:
        The modified constellation instance.
    """
    n = constellation.n[sat_index]
    u0_old = constellation.u0[sat_index]
    inc_old = constellation.inc[sat_index]

    # Direction of motion before rephasing (sign of dz/dt):
    # dz/dt = a * sin(inc) * cos(u(t)) * n.
    # Since a, sin(inc), n > 0, sign(dz/dt) == sign(cos(u_old(t))).
    u_old_at_t = u0_old + n * t
    is_north_going = np.cos(u_old_at_t) >= 0.0

    # Adjust inclination if |lat| exceeds it
    target_lat_rad = np.radians(lat_deg)
    target_lon_rad = np.radians(lon_deg)
    inc_new = max(inc_old, abs(target_lat_rad))

    # Solve for u(t) such that z = a * sin(inc) * sin(u) = a * sin(lat)
    sin_inc = np.sin(inc_new)
    if sin_inc == 0.0:
        sin_u = 0.0
    else:
        sin_u = np.clip(np.sin(target_lat_rad) / sin_inc, -1.0, 1.0)

    u_principal = np.arcsin(sin_u)
    # Principal arcsin gives cos(u) >= 0 (north-going).
    # pi - arcsin gives cos(u) <= 0 (south-going).
    if is_north_going:
        u_new_at_t = u_principal
    else:
        u_new_at_t = np.pi - u_principal

    # Solve for RAAN:
    # ECI longitude of target at time t: lon_eci = lon_ecef + OMEGA_E * t
    lon_eci = target_lon_rad + OMEGA_E * t

    # In orbital frame rotated by inclination inc:
    # x' = a cos(u), y' = a sin(u) cos(inc)
    # Rotating about z-axis by RAAN gives:
    # (x_eci + i y_eci) = e^(i * RAAN) * (x' + i y')
    # RAAN = lon_eci - atan2(y', x')
    alpha = np.arctan2(np.sin(u_new_at_t) * np.cos(inc_new), np.cos(u_new_at_t))
    raan_new = (lon_eci - alpha) % (2.0 * np.pi)

    # Solve for u0:
    # u(t) = u0 + n * t => u0 = (u(t) - n * t) mod 2pi
    u0_new = (u_new_at_t - n * t) % (2.0 * np.pi)

    # Update satellite orbital elements in place
    constellation.inc[sat_index] = inc_new
    constellation.raan[sat_index] = raan_new
    constellation.u0[sat_index] = u0_new

    return constellation


def ground_track(
    constellation: Constellation,
    sat_index: int,
    t0: float,
    t1: float,
    step: float,
) -> List[Tuple[float, float]]:
    """Compute ground track (latitude, longitude) of a satellite over time.

    Args:
        constellation: Constellation instance.
        sat_index: Satellite index.
        t0: Start time in seconds.
        t1: End time in seconds.
        step: Time step in seconds.

    Returns:
        List of (lat_deg, lon_deg) tuples.
    """
    if step <= 0:
        raise ValueError("step must be positive")

    if t1 < t0:
        return []

    t_steps = np.arange(t0, t1 + step * 0.5, step)

    a = constellation.a[sat_index]
    inc = constellation.inc[sat_index]
    raan = constellation.raan[sat_index]
    u0 = constellation.u0[sat_index]
    n = constellation.n[sat_index]

    u = u0 + n * t_steps
    cos_u = np.cos(u)
    sin_u = np.sin(u)
    cos_i = np.cos(inc)
    sin_i = np.sin(inc)
    cos_raan = np.cos(raan)
    sin_raan = np.sin(raan)

    # ECI
    x_prime = a * cos_u
    y_prime = a * sin_u * cos_i
    z_prime = a * sin_u * sin_i

    x_eci = x_prime * cos_raan - y_prime * sin_raan
    y_eci = x_prime * sin_raan + y_prime * cos_raan
    z_eci = z_prime

    # ECEF
    theta = -OMEGA_E * t_steps
    cos_th = np.cos(theta)
    sin_th = np.sin(theta)

    x_ecef = x_eci * cos_th - y_eci * sin_th
    y_ecef = x_eci * sin_th + y_eci * cos_th
    z_ecef = z_eci

    r_mag = np.sqrt(x_ecef**2 + y_ecef**2 + z_ecef**2)
    lat_deg = np.degrees(np.arcsin(np.clip(z_ecef / r_mag, -1.0, 1.0)))
    lon_deg = np.degrees(np.arctan2(y_ecef, x_ecef))

    return list(zip(lat_deg.tolist(), lon_deg.tolist()))
