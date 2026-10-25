"""Deterministic circular two-body propagation in Earth-centred inertial (ECI)."""

from __future__ import annotations

import math

from src.models.network import Position
from src.orbit.models import OrbitalElements

EARTH_MU_KM3_S2 = 398600.4418
EARTH_RADIUS_KM = 6378.137


def mean_motion_rad_s(semi_major_axis_km: float, mu_km3_s2: float = EARTH_MU_KM3_S2) -> float:
    if not math.isfinite(semi_major_axis_km) or semi_major_axis_km <= 0:
        raise ValueError("semi_major_axis_km must be finite and positive")
    if not math.isfinite(mu_km3_s2) or mu_km3_s2 <= 0:
        raise ValueError("mu_km3_s2 must be finite and positive")
    return math.sqrt(mu_km3_s2 / semi_major_axis_km**3)


def propagate_circular(elements: OrbitalElements, time_s: float,
                       mu_km3_s2: float = EARTH_MU_KM3_S2,
                       earth_radius_km: float = EARTH_RADIUS_KM) -> Position:
    """Propagate R3(RAAN) R1(inclination) R3(argument latitude) orbit to ECI."""
    if not math.isfinite(time_s):
        raise ValueError("time_s must be finite")
    if elements.semi_major_axis_km <= earth_radius_km:
        raise ValueError("semi-major axis must exceed the configured Earth radius")
    u = elements.argument_of_latitude_rad + mean_motion_rad_s(
        elements.semi_major_axis_km, mu_km3_s2) * (time_s - elements.epoch_s)
    inc, raan = elements.inclination_rad, elements.raan_rad
    cu, su = math.cos(u), math.sin(u)
    ci, si = math.cos(inc), math.sin(inc)
    co, so = math.cos(raan), math.sin(raan)
    a = elements.semi_major_axis_km
    return Position(a * (co * cu - so * su * ci),
                    a * (so * cu + co * su * ci),
                    a * su * si, frame="eci")
