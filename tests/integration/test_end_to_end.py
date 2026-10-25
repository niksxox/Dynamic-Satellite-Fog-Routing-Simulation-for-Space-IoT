"""Deterministic alternate-path scenario using physically eligible links."""

import math

from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Position, PacketState
from src.simulation import FailureSchedule, SimulationEngine
from src.traffic import TrafficSpec


def node(node_id, kind, x, y=0, **kwargs):
    return Node(node_id, kind, Position(x, y), **kwargs)


def _scenario(redundant=True):
    cfg = SimulationConfig(
        seed=4, duration_s=0.2, packet_timeout_s=0.1,
        topology_update_interval_s=0.05, iot_ground_range_km=20,
        satellite_range_km=2500, satellite_ground_range_km=2200,
        iot_satellite_range_km=1500, ground_fog_range_km=150,
        fog_cloud_range_km=1000, route_computation_delay_ms=1.0,
    )
    nodes = [
        node("iot", NodeType.IOT, 7000, -500),
        node("sat-a", NodeType.SATELLITE, 7000, 0,
             orbital_period_s=100_000, initial_orbital_phase_rad=0.0),
        node("sat-b", NodeType.SATELLITE, 6900, 100,
             orbital_period_s=100_000,
             initial_orbital_phase_rad=math.atan2(100, 6900)),
        node("gs", NodeType.GROUND_STATION, 7000, 1000),
        node("fog", NodeType.FOG, 7000, 1001, processing_capacity_pps=1000),
        node("cloud", NodeType.CLOUD, 7000, 1002),
    ]
    if not redundant:
        nodes[2] = node("sat-b", NodeType.SATELLITE, 0, 0,
                        orbital_period_s=100_000, initial_orbital_phase_rad=math.pi)
    traffic = [TrafficSpec("iot", "cloud", packet_size_bytes=512, schedule_s=(0.0,))]
    # Occurs while iot->sat-a is propagating; the next hop is then unavailable.
    failures = [FailureSchedule(0.0017, "link_failure", source="sat-a", target="gs")]
    return cfg, nodes, traffic, failures


def test_packet_reroutes_over_sat_b_after_sat_a_ground_link_failure():
    cfg, nodes, traffic, failures = _scenario()
    result = SimulationEngine(cfg, nodes, traffic, failures=failures).run()
    packet = result.packets[0]
    initial = next(d for d in result.routing_decisions if d.cause == "initial")
    recovery = next(d for d in result.routing_decisions if d.cause == "failure_recovery")
    assert initial.path[:3] == ("iot", "sat-a", "gs")
    assert recovery.path[:3] == ("sat-a", "sat-b", "gs")
    assert packet.state is PacketState.DELIVERED
    assert packet.reroute_count == 1
    assert packet.path == ["iot", "sat-a", "sat-b", "gs", "fog", "cloud"]
    assert recovery.recovery_time_s > 0
    assert packet.delivered_at_s - packet.generated_at_s == packet.latency_s
    assert not any(a == "sat-a" and b == "gs" for a, b in zip(packet.path, packet.path[1:]))
    assert any(e.event_type == "link_failure" for e in result.events)
    assert any(e.event_type == "route_changed" for e in result.events)
