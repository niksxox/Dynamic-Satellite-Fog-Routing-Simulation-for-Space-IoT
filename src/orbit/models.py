"""Typed orbital inputs. Distances are kilometres, angles radians, time seconds."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OrbitalElements:
    """Circular two-body elements at ``epoch_s`` in an Earth-centred inertial frame."""

    semi_major_axis_km: float
    inclination_rad: float = 0.0
    raan_rad: float = 0.0
    argument_of_latitude_rad: float = 0.0
    epoch_s: float = 0.0

    def __post_init__(self):
        values = (self.semi_major_axis_km, self.inclination_rad, self.raan_rad,
                  self.argument_of_latitude_rad, self.epoch_s)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("orbital elements must be finite")
        if self.semi_major_axis_km <= 0:
            raise ValueError("semi_major_axis_km must be positive")
        if not 0 <= self.inclination_rad <= math.pi:
            raise ValueError("inclination_rad must be between 0 and pi")


@dataclass(frozen=True, slots=True)
class GeodeticPosition:
    latitude_deg: float
    longitude_deg: float
    altitude_m: float = 0.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.latitude_deg, self.longitude_deg, self.altitude_m)):
            raise ValueError("geodetic coordinates must be finite")
        if not -90 <= self.latitude_deg <= 90:
            raise ValueError("latitude_deg must be in [-90, 90]")
        if not -180 <= self.longitude_deg <= 180:
            raise ValueError("longitude_deg must be in [-180, 180]")
        if not -1000 <= self.altitude_m <= 100_000:
            raise ValueError("altitude_m must be between -1000 and 100000 metres")
