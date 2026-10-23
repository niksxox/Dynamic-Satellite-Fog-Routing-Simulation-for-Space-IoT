import math

import pytest

from src.models.config import RoutingWeights, SimulationConfig
from src.models.network import Node, NodeType, Position
from src.topology.engine import TopologyEngine, distance_km, propagation_delay_ms, satellite_position


def node(name, kind, x, y=0, **kwargs):
    return Node(name, kind, Position(x, y), **kwargs)


def test_distance_and_propagation_units():
    assert distance_km(Position(0, 0), Position(3, 4)) == 5
    assert propagation_delay_ms(299_792.458) == pytest.approx(1000)
    with pytest.raises(ValueError):
        propagation_delay_ms(-1)


def test_satellite_position_is_deterministic_and_moves():
    sat = node("s", NodeType.SATELLITE, 7000, orbital_period_s=1000, initial_orbital_phase_rad=0)
    p0 = satellite_position(sat, 0)
    p1 = satellite_position(sat, 250)
    assert p0.x_km == pytest.approx(7000)
    assert p1.y_km == pytest.approx(7000)


def test_topology_creates_only_compatible_in_range_edges_and_updates():
    cfg = SimulationConfig(iot_ground_range_km=10, ground_fog_range_km=20)
    nodes = [node("iot", NodeType.IOT, 0), node("gs", NodeType.GROUND_STATION, 5),
             node("fog", NodeType.FOG, 15), node("cloud", NodeType.CLOUD, 16)]
    engine = TopologyEngine(cfg)
    graph = engine.initialize_network(nodes)
    assert graph.has_edge("iot", "gs")
    assert graph.has_edge("gs", "fog")
    assert graph.has_edge("fog", "cloud")


def test_link_events_are_emitted_only_on_topology_transitions():
    cfg = SimulationConfig(iot_ground_range_km=5)
    engine = TopologyEngine(cfg)
    engine.initialize_network([node("i", NodeType.IOT, 0), node("g", NodeType.GROUND_STATION, 4)])
    initial_count = len(engine.events)
    engine.update_topology(5)
    assert len(engine.events) == initial_count
    engine.nodes["g"].position = Position(20, 0)
    engine.update_topology(10)
    assert [event.event_type for event in engine.events] == ["link_up", "link_down"]


def test_operational_state_and_stats():
    engine = TopologyEngine(SimulationConfig(iot_ground_range_km=5))
    engine.initialize_network([node("i", NodeType.IOT, 0), node("g", NodeType.GROUND_STATION, 2)])
    engine.set_node_operational("g", False, 1)
    assert engine.topology_statistics() == {"nodes": 2, "operational_nodes": 1, "links": 0, "operational_links": 0}


def test_config_and_weight_validation():
    with pytest.raises(ValueError):
        RoutingWeights(0.4, 0.2, 0.2, 0.1)
    with pytest.raises(ValueError):
        SimulationConfig(duration_s=0)
