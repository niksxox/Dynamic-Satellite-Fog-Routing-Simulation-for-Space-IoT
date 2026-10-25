"""Range, same-frame distance, and oblate-Earth occultation checks."""

from __future__ import annotations

import math

from src.orbit.frames import ground_elevation_deg
from src.orbit.models import GeodeticPosition
from src.models.network import Position

GEOMETRY_TOLERANCE_KM = 1e-6
WGS84_FLATTENING = 1 / 298.257223563


def distance_km(a: Position, b: Position) -> float:
    if a.frame != "unspecified" and b.frame != "unspecified" and a.frame != b.frame:
        raise ValueError(f"cannot measure distance across frames: {a.frame} vs {b.frame}")
    return math.dist((a.x_km, a.y_km, a.z_km), (b.x_km, b.y_km, b.z_km))


def within_range(a: Position, b: Position, max_range_km: float,
                 tolerance_km: float = GEOMETRY_TOLERANCE_KM) -> bool:
    if not math.isfinite(max_range_km) or not math.isfinite(tolerance_km) or max_range_km <= 0 or tolerance_km < 0:
        raise ValueError("range must be positive and tolerance nonnegative")
    return distance_km(a, b) <= max_range_km + tolerance_km


def line_of_sight(a: Position, b: Position, earth_radius_km: float,
                  tolerance_km: float = GEOMETRY_TOLERANCE_KM,
                  flattening: float = WGS84_FLATTENING) -> bool:
    """Return false if the open segment intersects the reference Earth ellipsoid.

    The 1-metre default tolerance avoids classifying roundoff at a tangency as
    an occultation while preserving a conservative, explicit boundary.
    """
    if a.frame != "unspecified" and b.frame != "unspecified" and a.frame != b.frame:
        raise ValueError("line-of-sight endpoints must share a coordinate frame")
    if earth_radius_km <= 0 or tolerance_km < 0:
        raise ValueError("earth radius must be positive and tolerance nonnegative")
    if not 0 <= flattening < 1 or not math.isfinite(flattening):
        raise ValueError("flattening must be finite and in [0, 1)")
    polar_radius = earth_radius_km * (1-flattening)
    av = (a.x_km/earth_radius_km, a.y_km/earth_radius_km, a.z_km/polar_radius)
    bv = (b.x_km/earth_radius_km, b.y_km/earth_radius_km, b.z_km/polar_radius)
    if (math.sqrt(sum(v*v for v in av)) < 1-tolerance_km/earth_radius_km or
            math.sqrt(sum(v*v for v in bv)) < 1-tolerance_km/earth_radius_km):
        return False
    dx = tuple(bv[i] - av[i] for i in range(3))
    length2 = sum(v*v for v in dx)
    if length2 == 0:
        return math.sqrt(sum(v*v for v in av)) >= earth_radius_km - tolerance_km
    t = max(0.0, min(1.0, -sum(av[i]*dx[i] for i in range(3)) / length2))
    closest = tuple(av[i] + t*dx[i] for i in range(3))
    minimum = math.sqrt(sum(v*v for v in closest))
    # A ground endpoint can lie on the reference surface; only interior Earth
    # penetration blocks the link. At a true tangent, tolerance accepts LOS.
    near_endpoint = (tolerance_km / earth_radius_km) / max(math.sqrt(length2), 1e-12)
    if t <= near_endpoint or 1-t <= near_endpoint:
        return True
    return minimum >= 1 - tolerance_km/earth_radius_km


def satellite_to_satellite_eligible(a: Position, b: Position, max_range_km: float,
                                    earth_radius_km: float,
                                    flattening: float = WGS84_FLATTENING) -> bool:
    return within_range(a, b, max_range_km) and line_of_sight(a, b, earth_radius_km, flattening=flattening)


def satellite_to_ground_eligible(satellite_eci: Position, station_ecef: Position,
        station_geodetic: GeodeticPosition, time_s: float, max_range_km: float,
        earth_radius_km: float, minimum_elevation_deg: float,
        reference_epoch_unix_s: float,
        flattening: float = WGS84_FLATTENING) -> tuple[bool, dict[str, float | bool]]:
    """Visibility requires range, ECI/ECEF-consistent LOS, and minimum elevation."""
    from src.orbit.frames import ecef_to_eci
    station_eci = ecef_to_eci(station_ecef, time_s, reference_epoch_unix_s)
    distance = distance_km(satellite_eci, station_eci)
    los = line_of_sight(satellite_eci, station_eci, earth_radius_km, flattening=flattening)
    elevation = ground_elevation_deg(satellite_eci, station_ecef, station_geodetic,
                                     time_s, reference_epoch_unix_s)
    visible = (distance <= max_range_km + GEOMETRY_TOLERANCE_KM and los and
               elevation + 1e-9 >= minimum_elevation_deg)
    return visible, {"distance_km": distance, "line_of_sight": los,
                     "elevation_deg": elevation}
