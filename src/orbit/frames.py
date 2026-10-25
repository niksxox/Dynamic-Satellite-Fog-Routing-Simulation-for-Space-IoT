"""WGS-84 ground coordinates and simplified UT1=UTC ECI/ECEF transforms."""

from __future__ import annotations

import math

from src.models.network import Position
from src.orbit.models import GeodeticPosition

WGS84_SEMI_MAJOR_KM = 6378.137
WGS84_FLATTENING = 1 / 298.257223563
EARTH_ROTATION_RAD_S = 7.2921150e-5
J2000_UNIX_S = 946728000.0
SECONDS_PER_DAY = 86400.0


def geodetic_to_ecef(position: GeodeticPosition, semi_major_km: float = WGS84_SEMI_MAJOR_KM,
                     flattening: float = WGS84_FLATTENING) -> Position:
    """WGS-84 geodetic latitude/longitude degrees, altitude metres -> ECEF km."""
    lat, lon = math.radians(position.latitude_deg), math.radians(position.longitude_deg)
    altitude_km = position.altitude_m / 1000.0
    e2 = flattening * (2 - flattening)
    n = semi_major_km / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return Position((n + altitude_km) * math.cos(lat) * math.cos(lon),
                    (n + altitude_km) * math.cos(lat) * math.sin(lon),
                    (n * (1 - e2) + altitude_km) * math.sin(lat), frame="ecef")


def ecef_to_geodetic(position: Position, semi_major_km: float = WGS84_SEMI_MAJOR_KM,
                     flattening: float = WGS84_FLATTENING) -> GeodeticPosition:
    """Convert WGS-84 ECEF km to geodetic degrees and altitude metres."""
    if position.frame not in {"ecef", "unspecified"}:
        raise ValueError("ecef_to_geodetic requires an ECEF position")
    x, y, z = position.x_km, position.y_km, position.z_km
    a, f = semi_major_km, flattening
    e2 = f * (2 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(8):
        n = a / math.sqrt(1 - e2 * math.sin(lat)**2)
        altitude = p / max(math.cos(lat), 1e-15) - n
        lat_next = math.atan2(z, p * (1 - e2 * n / (n + altitude)))
        if abs(lat_next - lat) < 1e-13:
            lat = lat_next
            break
        lat = lat_next
    n = a / math.sqrt(1 - e2 * math.sin(lat)**2)
    altitude = p / max(abs(math.cos(lat)), 1e-15) - n if abs(lat) < math.pi/2 - 1e-8 else abs(z)-n*(1-e2)
    return GeodeticPosition(math.degrees(lat), math.degrees(lon), altitude * 1000)


def earth_rotation_angle_rad(unix_time_s: float) -> float:
    """IAU Earth Rotation Angle using UT1=UTC, with no polar-motion correction."""
    if not math.isfinite(unix_time_s):
        raise ValueError("reference epoch must be finite")
    jd = unix_time_s / SECONDS_PER_DAY + 2440587.5
    turns = 0.7790572732640 + 1.00273781191135448 * (jd - 2451545.0)
    return 2 * math.pi * (turns % 1.0)


def ecef_to_eci(position: Position, sim_time_s: float,
                reference_epoch_unix_s: float = J2000_UNIX_S) -> Position:
    if position.frame not in {"ecef", "unspecified"}:
        raise ValueError("ecef_to_eci requires an ECEF position")
    angle = earth_rotation_angle_rad(reference_epoch_unix_s + sim_time_s)
    c, s = math.cos(angle), math.sin(angle)
    return Position(c * position.x_km - s * position.y_km,
                    s * position.x_km + c * position.y_km,
                    position.z_km, frame="eci")


def eci_to_ecef(position: Position, sim_time_s: float,
                reference_epoch_unix_s: float = J2000_UNIX_S) -> Position:
    if position.frame not in {"eci", "unspecified"}:
        raise ValueError("eci_to_ecef requires an ECI position")
    angle = earth_rotation_angle_rad(reference_epoch_unix_s + sim_time_s)
    c, s = math.cos(angle), math.sin(angle)
    return Position(c * position.x_km + s * position.y_km,
                    -s * position.x_km + c * position.y_km,
                    position.z_km, frame="ecef")


def ground_elevation_deg(satellite_eci: Position, station_ecef: Position,
                         station: GeodeticPosition, sim_time_s: float,
                         reference_epoch_unix_s: float = J2000_UNIX_S) -> float:
    """Topocentric elevation from ECI satellite using station-local ENU axes."""
    sat = eci_to_ecef(satellite_eci, sim_time_s, reference_epoch_unix_s)
    dx, dy, dz = sat.x_km-station_ecef.x_km, sat.y_km-station_ecef.y_km, sat.z_km-station_ecef.z_km
    lat, lon = math.radians(station.latitude_deg), math.radians(station.longitude_deg)
    east = -math.sin(lon)*dx + math.cos(lon)*dy
    north = -math.sin(lat)*math.cos(lon)*dx - math.sin(lat)*math.sin(lon)*dy + math.cos(lat)*dz
    up = math.cos(lat)*math.cos(lon)*dx + math.cos(lat)*math.sin(lon)*dy + math.sin(lat)*dz
    return math.degrees(math.atan2(up, math.hypot(east, north)))
