import math

import pytest

from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Position
from src.orbit.frames import (J2000_UNIX_S, ecef_to_eci, eci_to_ecef,
    earth_rotation_angle_rad, geodetic_to_ecef, ground_elevation_deg)
from src.orbit.geometry import (distance_km, line_of_sight,
    satellite_to_ground_eligible, satellite_to_satellite_eligible)
from src.orbit.models import GeodeticPosition, OrbitalElements
from src.orbit.propagation import mean_motion_rad_s, propagate_circular
from src.topology.engine import TopologyEngine


def test_circular_propagation_radius_phase_and_determinism():
    orbit = OrbitalElements(6928.137, inclination_rad=0.4, raan_rad=0.7,
                           argument_of_latitude_rad=0.2)
    quarter = math.pi / (2 * mean_motion_rad_s(orbit.semi_major_axis_km))
    p0 = propagate_circular(orbit, 0)
    p1 = propagate_circular(orbit, quarter)
    assert math.isclose(distance_km(Position(0, 0, 0, "eci"), p0), orbit.semi_major_axis_km, abs_tol=1e-9)
    assert math.isclose(distance_km(Position(0, 0, 0, "eci"), p1), orbit.semi_major_axis_km, abs_tol=1e-9)
    assert p1 == propagate_circular(orbit, quarter)
    other_plane = propagate_circular(OrbitalElements(orbit.semi_major_axis_km,
        inclination_rad=1.0, raan_rad=1.2, argument_of_latitude_rad=0.2), quarter)
    assert distance_km(p1, other_plane) > 100


def test_ecef_eci_round_trip_and_wgs84_equator():
    surface = geodetic_to_ecef(GeodeticPosition(0, 0))
    assert math.isclose(surface.x_km, 6378.137, abs_tol=1e-9)
    p = Position(4100, -2500, 3000, "ecef")
    assert distance_km(p, eci_to_ecef(ecef_to_eci(p, 123.4), 123.4)) < 1e-9
    assert abs(earth_rotation_angle_rad(J2000_UNIX_S + 1) -
               earth_rotation_angle_rad(J2000_UNIX_S) - 7.292115e-5) < 2e-8


def test_range_and_earth_occultation():
    a, b = Position(7000, 0, 0, "eci"), Position(7100, 0, 0, "eci")
    assert satellite_to_satellite_eligible(a, b, 200, 6378.137)
    assert not satellite_to_satellite_eligible(a, Position(8000, 0, 0, "eci"), 500, 6378.137)
    opposite_a, opposite_b = Position(-7000, 0, 0, "eci"), Position(7000, 0, 0, "eci")
    assert not line_of_sight(opposite_a, opposite_b, 6378.137)
    with pytest.raises(ValueError):
        distance_km(Position(1, 2, 3, "eci"), Position(1, 2, 3, "ecef"))


def test_ground_elevation_and_visibility_threshold():
    geo = GeodeticPosition(0, 0)
    ecef = geodetic_to_ecef(geo)
    station_eci = ecef_to_eci(ecef, 0)
    overhead = Position(station_eci.x_km * (6928.137 / 6378.137),
        station_eci.y_km * (6928.137 / 6378.137), 0, "eci")
    assert math.isclose(ground_elevation_deg(overhead, ecef, geo, 0), 90, abs_tol=1e-7)
    eligible, _ = satellite_to_ground_eligible(overhead, ecef, geo, 0, 1000,
        6378.137, 10, J2000_UNIX_S)
    assert eligible
    below_horizon = Position(-overhead.x_km, -overhead.y_km, 0, "eci")
    eligible, details = satellite_to_ground_eligible(below_horizon, ecef, geo, 0,
        20000, 6378.137, 0, J2000_UNIX_S)
    assert not eligible and details["elevation_deg"] < 0


def test_topology_recomputes_visibility_and_preserves_admin_failure():
    config = SimulationConfig(orbital_model="circular_two_body", duration_s=600,
        topology_update_interval_s=5, satellite_ground_range_km=2200,
        minimum_ground_elevation_deg=10)
    station = geodetic_to_ecef(GeodeticPosition(0, 0))
    phase = earth_rotation_angle_rad(config.reference_epoch_unix_s)
    sat = Node("sat", NodeType.SATELLITE, Position(6928.137, 0, 0, "eci"),
        orbit=OrbitalElements(6928.137, argument_of_latitude_rad=phase))
    gs = Node("gs", NodeType.GROUND_STATION, station, latitude_deg=0, longitude_deg=0)
    engine = TopologyEngine(config)
    engine.initialize_network([sat, gs])
    assert engine.graph.has_edge("sat", "gs")
    engine.set_link_operational("sat", "gs", False, 0)
    assert engine.graph.has_edge("sat", "gs") and not engine.graph.edges["sat", "gs"]["operational"]
    engine.update_topology(500)
    assert not engine.graph.has_edge("sat", "gs")
    engine.set_link_operational("sat", "gs", True, 500)
    assert not engine.graph.has_edge("sat", "gs")
    engine.update_topology(0)
    assert engine.graph.has_edge("sat", "gs")
    assert engine.graph.edges["sat", "gs"]["operational"]


def test_validation_rejects_impossible_orbit_and_geodetic_values():
    with pytest.raises(ValueError):
        propagate_circular(OrbitalElements(6300), 0)
    with pytest.raises(ValueError):
        GeodeticPosition(91, 0)
    with pytest.raises(ValueError):
        Position(float("nan"), 0)
