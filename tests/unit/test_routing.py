"""Unit tests for the Dijkstra routing engine."""

import math

import networkx as nx
import pytest

from src.models.config import RoutingWeights, SimulationConfig
from src.models.network import Node, NodeType, Position
from src.routing import RoutingEngine, RoutingMode
from src.topology.engine import TopologyEngine


def _node(node_id, kind, x=0.0, y=0.0, **kwargs):
    return Node(node_id, kind, Position(x, y), **kwargs)


def _add_node(graph, node_id, kind, operational=True):
    graph.add_node(
        node_id,
        model=_node(node_id, kind),
        node_type=kind.value,
        operational=operational,
        position=Position(0.0, 0.0),
    )


def _add_link(graph, u, v, latency, bandwidth, loss=0.0, congestion=0.0, operational=True):
    graph.add_edge(
        u,
        v,
        distance_km=1.0,
        propagation_latency_ms=latency,
        bandwidth_mbps=bandwidth,
        packet_loss_probability=loss,
        congestion=congestion,
        operational=operational,
    )


def _diamond_graph():
    """A→B→D is fastest (20 ms); A→C→D is best quality (1000 Mbps, no loss).

    Shortest-latency and multi-factor routing pick different paths.
    """
    graph = nx.Graph()
    for nid in ("A", "B", "C", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0, 0.1, 0.1)
    _add_link(graph, "B", "D", 10.0, 100.0, 0.1, 0.1)
    _add_link(graph, "A", "C", 20.0, 1000.0, 0.0, 0.0)
    _add_link(graph, "C", "D", 20.0, 1000.0, 0.0, 0.0)
    _add_link(graph, "A", "D", 100.0, 10.0, 0.0, 0.0)
    return graph


engine = RoutingEngine()


def test_shortest_latency_selects_fastest_path():
    result = engine.route(_diamond_graph(), "A", "D", RoutingMode.SHORTEST_LATENCY)
    assert result.route_available
    assert result.algorithm == "shortest_latency"
    assert result.path == ["A", "B", "D"]
    assert result.total_cost == pytest.approx(20.0)
    assert result.estimated_latency_ms == pytest.approx(20.0)
    assert result.bottleneck_bandwidth_mbps == pytest.approx(100.0)
    assert result.delivery_reliability == pytest.approx(0.9 * 0.9)
    assert result.reason is None


def test_multi_factor_selects_high_quality_path():
    result = engine.route(_diamond_graph(), "A", "D", RoutingMode.MULTI_FACTOR)
    assert result.route_available
    assert result.algorithm == "multi_factor"
    assert result.path == ["A", "C", "D"]
    # Normalized cost: 2 * (0.45 * (20-10)/90) = 0.1
    assert result.total_cost == pytest.approx(0.1, rel=1e-9)
    assert result.estimated_latency_ms == pytest.approx(40.0)
    assert result.bottleneck_bandwidth_mbps == pytest.approx(1000.0)
    assert result.delivery_reliability == pytest.approx(1.0)
    assert result.reason is None


def test_algorithms_choose_different_paths():
    graph = _diamond_graph()
    latency_result = engine.route(graph, "A", "D", RoutingMode.SHORTEST_LATENCY)
    multi_result = engine.route(graph, "A", "D", RoutingMode.MULTI_FACTOR)
    assert latency_result.path != multi_result.path
    assert latency_result.path == ["A", "B", "D"]
    assert multi_result.path == ["A", "C", "D"]


def test_bandwidth_penalty_direction_higher_bandwidth_lower_cost():
    graph = nx.Graph()
    for nid in ("A", "B", "C", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0)
    _add_link(graph, "B", "D", 10.0, 100.0)
    _add_link(graph, "A", "C", 10.0, 1000.0)
    _add_link(graph, "C", "D", 10.0, 1000.0)
    result = engine.route(graph, "A", "D", RoutingMode.MULTI_FACTOR)
    assert result.route_available
    assert result.path == ["A", "C", "D"]
    assert result.bottleneck_bandwidth_mbps == pytest.approx(1000.0)


def test_loss_increases_multi_factor_cost():
    graph = nx.Graph()
    for nid in ("A", "B", "C", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0, 0.5)
    _add_link(graph, "B", "D", 10.0, 100.0, 0.5)
    _add_link(graph, "A", "C", 10.0, 100.0, 0.0)
    _add_link(graph, "C", "D", 10.0, 100.0, 0.0)
    result = engine.route(graph, "A", "D", RoutingMode.MULTI_FACTOR)
    assert result.route_available
    assert result.path == ["A", "C", "D"]


def test_congestion_increases_multi_factor_cost():
    graph = nx.Graph()
    for nid in ("A", "B", "C", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0, 0.0, 0.5)
    _add_link(graph, "B", "D", 10.0, 100.0, 0.0, 0.5)
    _add_link(graph, "A", "C", 10.0, 100.0, 0.0, 0.0)
    _add_link(graph, "C", "D", 10.0, 100.0, 0.0, 0.0)
    result = engine.route(graph, "A", "D", RoutingMode.MULTI_FACTOR)
    assert result.route_available
    assert result.path == ["A", "C", "D"]


def test_weights_steer_routing_toward_latency():
    graph = _diamond_graph()
    result = engine.route(
        graph,
        "A",
        "D",
        RoutingMode.MULTI_FACTOR,
        weights=RoutingWeights(1.0, 0.0, 0.0, 0.0),
    )
    assert result.route_available
    assert result.path == ["A", "B", "D"]


def test_weight_validation():
    with pytest.raises(ValueError):
        RoutingWeights(0.5, 0.3, 0.1, 0.2)  # sums to 1.1
    with pytest.raises(ValueError):
        RoutingWeights(-0.1, 0.4, 0.4, 0.3)


def test_no_available_path():
    graph = nx.Graph()
    for nid in ("A", "B", "C", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0)
    _add_link(graph, "C", "D", 10.0, 100.0)
    result = engine.route(graph, "A", "C")
    assert not result.route_available
    assert result.reason == "no available path"
    assert result.path == []
    assert not math.isfinite(result.total_cost)
    assert result.delivery_reliability == 0.0


def test_unknown_source_and_destination():
    graph = _diamond_graph()
    result = engine.route(graph, "ZZZ", "D")
    assert not result.route_available
    assert result.reason == "unknown source node"
    result = engine.route(graph, "A", "ZZZ")
    assert not result.route_available
    assert result.reason == "unknown destination node"


def test_failed_source_or_destination():
    graph = _diamond_graph()
    graph.nodes["A"]["operational"] = False
    result = engine.route(graph, "A", "D")
    assert not result.route_available
    assert result.reason == "source node is not operational"

    graph.nodes["A"]["operational"] = True
    graph.nodes["D"]["operational"] = False
    result = engine.route(graph, "A", "D")
    assert not result.route_available
    assert result.reason == "destination node is not operational"


def test_unavailable_edge_is_never_traversed():
    graph = _diamond_graph()
    graph.edges["A", "B"]["operational"] = False
    result = engine.route(graph, "A", "D", RoutingMode.SHORTEST_LATENCY)
    assert result.route_available
    assert "B" not in result.path
    assert result.path == ["A", "C", "D"]


def test_trivial_route_source_equals_destination():
    result = engine.route(_diamond_graph(), "A", "A")
    assert result.route_available
    assert result.path == ["A"]
    assert result.total_cost == 0.0
    assert result.estimated_latency_ms == 0.0
    assert math.isinf(result.bottleneck_bandwidth_mbps)
    assert result.delivery_reliability == 1.0
    assert result.reason is None


def test_path_latency_includes_propagation_and_transmission_overhead():
    graph = nx.Graph()
    for nid in ("A", "B", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0, 0.0, 0.0)
    graph.edges["A", "B"]["transmission_overhead_ms"] = 2.0
    _add_link(graph, "B", "D", 10.0, 100.0, 0.0, 0.0)
    graph.edges["B", "D"]["transmission_overhead_ms"] = 3.0
    result = engine.route(graph, "A", "D", RoutingMode.SHORTEST_LATENCY)
    assert result.route_available
    assert result.estimated_latency_ms == pytest.approx(25.0)
    assert result.total_cost == pytest.approx(25.0)


def test_packet_size_dependent_transmission_delay_is_optional():
    graph = nx.Graph()
    for nid in ("A", "B"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0)
    without = engine.route(graph, "A", "B", packet_size_bytes=None)
    with_size = engine.route(graph, "A", "B", packet_size_bytes=10_000)
    assert without.estimated_latency_ms == pytest.approx(10.0)
    # 10000 bytes * 8 bits / (100 Mbps * 1e6) s = 0.8 ms
    assert with_size.estimated_latency_ms == pytest.approx(10.8)


def test_bottleneck_bandwidth_is_minimum_hop_bandwidth():
    graph = nx.Graph()
    for nid in ("A", "B", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0)
    _add_link(graph, "B", "D", 10.0, 50.0)
    result = engine.route(graph, "A", "D", RoutingMode.SHORTEST_LATENCY)
    assert result.route_available
    assert result.bottleneck_bandwidth_mbps == pytest.approx(50.0)


def test_reliability_is_product_of_link_success_probabilities():
    graph = nx.Graph()
    for nid in ("A", "B", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0, 0.1)
    _add_link(graph, "B", "D", 10.0, 100.0, 0.2)
    result = engine.route(graph, "A", "D", RoutingMode.SHORTEST_LATENCY)
    assert result.route_available
    assert result.delivery_reliability == pytest.approx(0.9 * 0.8)


def test_missing_loss_probability_defaults_to_zero():
    graph = nx.Graph()
    for nid in ("A", "B"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    graph.add_edge(
        "A", "B", distance_km=1.0, propagation_latency_ms=10.0,
        bandwidth_mbps=100.0, congestion=0.0, operational=True,
    )
    result = engine.route(graph, "A", "B")
    assert result.route_available
    assert result.delivery_reliability == pytest.approx(1.0)


def test_invalid_edge_attributes_are_excluded():
    graph = nx.Graph()
    for nid in ("A", "B", "D"):
        _add_node(graph, nid, NodeType.GROUND_STATION)
    _add_link(graph, "A", "B", 10.0, 100.0)
    graph.edges["A", "B"]["bandwidth_mbps"] = -1.0  # invalid
    _add_link(graph, "B", "D", 10.0, 100.0)
    result = engine.route(graph, "A", "D", RoutingMode.SHORTEST_LATENCY)
    assert not result.route_available
    assert result.reason == "no available path"


def test_route_does_not_mutate_input_graph():
    graph = _diamond_graph()
    snapshot = {
        (u, v): bool(d["operational"])
        for u, v, d in graph.edges(data=True)
    }
    edge_count = graph.number_of_edges()
    engine.route(graph, "A", "D", RoutingMode.MULTI_FACTOR)
    engine.route(graph, "A", "D", RoutingMode.SHORTEST_LATENCY)
    assert graph.number_of_edges() == edge_count
    assert {
        (u, v): bool(d["operational"])
        for u, v, d in graph.edges(data=True)
    } == snapshot


def test_failed_link_persists_across_topology_updates_and_recovers_explicitly():
    cfg = SimulationConfig(iot_ground_range_km=50.0)
    topo = TopologyEngine(cfg)
    topo.initialize_network([
        _node("iot", NodeType.IOT, 0, 0),
        _node("gs", NodeType.GROUND_STATION, 10, 0),
    ])
    router = RoutingEngine(cfg)
    assert router.route(topo.graph, "iot", "gs").route_available

    # Explicit failure: link excluded from routes.
    topo.set_link_operational("iot", "gs", False, 1.0)
    assert not router.route(topo.graph, "iot", "gs").route_available

    # Subsequent topology updates with unchanged physics must not reactivate it.
    topo.update_topology(2.0)
    assert frozenset(("iot", "gs")) in topo.failed_links
    assert not router.route(topo.graph, "iot", "gs").route_available

    # Leave range and come back: explicit failure must survive reconciliation.
    topo.nodes["gs"].position = Position(100, 0)
    topo.update_topology(3.0)
    topo.nodes["gs"].position = Position(10, 0)
    topo.update_topology(4.0)
    assert topo.graph.has_edge("iot", "gs")
    assert not bool(topo.graph.edges["iot", "gs"]["operational"])
    assert not router.route(topo.graph, "iot", "gs").route_available

    # Explicit recovery restores the link when physically eligible.
    topo.set_link_operational("iot", "gs", True, 5.0)
    result = router.route(topo.graph, "iot", "gs")
    assert result.route_available
    assert result.path == ["iot", "gs"]
    assert result.estimated_latency_ms > 0.0
