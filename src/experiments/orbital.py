"""Helpers for applying explicit orbital demo settings to a scenario."""

from dataclasses import replace
import math

from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Position
from src.orbit.frames import earth_rotation_angle_rad, geodetic_to_ecef
from src.orbit.models import GeodeticPosition, OrbitalElements


def apply_orbital_settings(config: SimulationConfig, nodes: list[Node], *,
        orbital_model: str | None = None, altitude_km: float = 550.0,
        inclination_deg: float = 53.0, raan_deg: float = 0.0,
        argument_of_latitude_deg: float = 0.0, station_latitude_deg: float = 0.0,
        station_longitude_deg: float = 0.0, station_altitude_m: float = 0.0,
        minimum_elevation_deg: float | None = None):
    """Return a config/node set in legacy XY or coherent ECI/ECEF coordinates."""
    model = orbital_model or config.orbital_model
    if model == "legacy_xy":
        return replace(config, orbital_model=model), nodes
    if model != "circular_two_body":
        raise ValueError("orbital_model must be legacy_xy or circular_two_body")
    if not math.isfinite(altitude_km) or altitude_km <= 0:
        raise ValueError("satellite altitude_km must be finite and positive")
    if minimum_elevation_deg is None:
        minimum_elevation_deg = config.minimum_ground_elevation_deg
    updated_config = replace(config, orbital_model=model,
        minimum_ground_elevation_deg=minimum_elevation_deg)
    output = []
    station = GeodeticPosition(station_latitude_deg, station_longitude_deg, station_altitude_m)
    phase0 = (earth_rotation_angle_rad(updated_config.reference_epoch_unix_s) +
              math.radians(argument_of_latitude_deg))
    for node in nodes:
        if node.node_type is NodeType.SATELLITE:
            index = int(node.node_id.rsplit("-", 1)[-1]) if node.node_id.rsplit("-", 1)[-1].isdigit() else len(output)
            offset = (index - 1) * 0.003
            orbit = OrbitalElements(updated_config.earth_radius_km + altitude_km,
                inclination_rad=math.radians(inclination_deg),
                raan_rad=math.radians(raan_deg) + offset,
                argument_of_latitude_rad=phase0 + offset)
            output.append(replace(node, position=Position(orbit.semi_major_axis_km, 0, 0, "eci"), orbit=orbit))
        else:
            if node.node_type is NodeType.GROUND_STATION:
                geo = station
            elif node.node_type is NodeType.IOT:
                geo = GeodeticPosition(station.latitude_deg,
                    max(-180, min(180, station.longitude_deg + 0.22)), station.altitude_m)
            elif node.node_type is NodeType.FOG:
                geo = GeodeticPosition(station.latitude_deg, station.longitude_deg + 0.005, station.altitude_m)
            else:
                geo = GeodeticPosition(station.latitude_deg, station.longitude_deg + 0.01, station.altitude_m)
            output.append(replace(node, position=geodetic_to_ecef(geo, updated_config.earth_radius_km,
                updated_config.earth_flattening), latitude_deg=geo.latitude_deg,
                longitude_deg=geo.longitude_deg, altitude_m=geo.altitude_m))
    return updated_config, output
