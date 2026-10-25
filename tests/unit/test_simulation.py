import pytest

from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Position, PacketState
from src.simulation import FailureSchedule, SimulationEngine, transmission_delay_s
from src.traffic import TrafficSpec


def n(node_id, kind, x, y=0, **kwargs):
    return Node(node_id, kind, Position(x, y), **kwargs)


def test_transmission_delay_units():
    assert transmission_delay_s(1_000_000, 8) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        transmission_delay_s(0, 10)
    with pytest.raises(ValueError):
        transmission_delay_s(1, 0)


def _direct_sim(seed=19, packet_size=100, duration=10, timeout=20, rate=1.0):
    cfg = SimulationConfig(seed=seed, duration_s=duration, packet_timeout_s=timeout,
                           topology_update_interval_s=100, iot_ground_range_km=10)
    nodes = [n("iot", NodeType.IOT, 0), n("gs", NodeType.GROUND_STATION, 1)]
    traffic = [TrafficSpec("iot", "gs", rate, packet_size)]
    return SimulationEngine(cfg, nodes, traffic)


def test_deterministic_schedule_delivery_and_lifecycle():
    engine = _direct_sim(duration=2)
    engine.traffic = [TrafficSpec("iot", "gs", packet_size_bytes=500,
                                  schedule_s=(0.0, 0.5))]
    result = engine.run()
    assert result.metrics.generated == 2
    assert result.metrics.delivered == 2
    assert all(p.state is PacketState.DELIVERED for p in result.packets)
    assert all(p.latency_s == pytest.approx(p.delivered_at_s - p.generated_at_s)
               for p in result.packets)
    assert len({p.packet_id for p in result.packets}) == 2


def test_fixed_seed_reproduces_poisson_arrival_records():
    def sample():
        return [(p.generated_at_s, p.state, p.path)
                for p in _direct_sim(seed=52, duration=4, rate=2).run().packets]
    assert sample() == sample()


def test_packet_loss_uses_seeded_loss_decision():
    cfg = SimulationConfig(duration_s=1, packet_timeout_s=2,
                           topology_update_interval_s=10, iot_ground_range_km=10)
    schedule = FailureSchedule(0, "packet_loss_change", source="iot", target="gs", value=1.0)
    result = SimulationEngine(
        cfg, [n("iot", NodeType.IOT, 0), n("gs", NodeType.GROUND_STATION, 1)],
        [TrafficSpec("iot", "gs", packet_size_bytes=100, schedule_s=(0,))],
        failures=[schedule],
    ).run()
    assert result.metrics.dropped == 1
    assert result.packets[0].state is PacketState.DROPPED
    assert result.packets[0].delivered_at_s is None


def test_frame_already_serializing_completes_after_link_failure():
    cfg = SimulationConfig(duration_s=10, packet_timeout_s=20,
                           topology_update_interval_s=50, iot_ground_range_km=2)
    nodes = [n("iot", NodeType.IOT, 0, bandwidth_mbps=1),
             n("gs", NodeType.GROUND_STATION, 1, bandwidth_mbps=1)]
    schedule = FailureSchedule(0.1, "link_failure", source="iot", target="gs")
    traffic = [TrafficSpec("iot", "gs", packet_size_bytes=1_000_000,
                           schedule_s=(0.0,))]
    result = SimulationEngine(cfg, nodes, traffic, failures=[schedule]).run()
    assert result.metrics.delivered == 1
    assert result.packets[0].state is PacketState.DELIVERED
    failure = next(e for e in result.events if e.event_type == "link_failure")
    delivery = next(e for e in result.events if e.event_type == "packet_delivered")
    assert failure.timestamp_s < delivery.timestamp_s


def test_link_resource_serializes_concurrent_packets():
    cfg = SimulationConfig(duration_s=20, packet_timeout_s=19,
                           topology_update_interval_s=100, iot_ground_range_km=2)
    nodes = [n("iot", NodeType.IOT, 0, bandwidth_mbps=1),
             n("gs", NodeType.GROUND_STATION, 1, bandwidth_mbps=1)]
    traffic = [TrafficSpec("iot", "gs", packet_size_bytes=1_000_000,
                           schedule_s=(0, 0.001))]
    result = SimulationEngine(cfg, nodes, traffic).run()
    assert result.metrics.delivered == 2
    assert result.packets[1].delivered_at_s - result.packets[0].delivered_at_s > 7.9


def test_packet_timeout_and_horizon_censoring_are_distinct():
    timeout_result = _direct_sim(duration=2, timeout=0.05,
                                 packet_size=10_000_000).run()
    assert timeout_result.metrics.timed_out == 1
    assert timeout_result.metrics.pending == 0

    censored_engine = _direct_sim(duration=0.00001, timeout=10, packet_size=100_000)
    censored_engine.traffic = [TrafficSpec("iot", "gs", packet_size_bytes=100_000,
                                           schedule_s=(0.0,))]
    censored = censored_engine.run()
    assert censored.metrics.pending == 1
    assert censored.metrics.delivered == 0
    assert censored.packets[0].state is PacketState.PENDING


def test_no_alternate_route_drops_after_bounded_retries():
    cfg = SimulationConfig(duration_s=3, packet_timeout_s=2,
                           topology_update_interval_s=0.5,
                           iot_ground_range_km=10, iot_satellite_range_km=1500,
                           satellite_ground_range_km=2200, max_packet_retries=1)
    nodes = [
        n("iot", NodeType.IOT, 7000, -500),
        n("sat", NodeType.SATELLITE, 7000, 0, orbital_period_s=100_000),
        n("gs", NodeType.GROUND_STATION, 7000, 1000),
    ]
    schedule = FailureSchedule(0.00165, "link_failure", source="sat", target="gs")
    result = SimulationEngine(
        cfg, nodes,
        [TrafficSpec("iot", "gs", packet_size_bytes=512, schedule_s=(0,))],
        failures=[schedule],
    ).run()
    assert result.metrics.dropped == 1
    assert result.metrics.recovery_failures == 1


def test_fog_queue_delay_is_measured_from_resource_wait():
    cfg = SimulationConfig(duration_s=4, packet_timeout_s=10,
                           topology_update_interval_s=20,
                           iot_ground_range_km=10, ground_fog_range_km=10,
                           fog_cloud_range_km=10)
    nodes = [
        n("iot", NodeType.IOT, 0), n("gs", NodeType.GROUND_STATION, 1),
        n("fog", NodeType.FOG, 2, processing_capacity_pps=1),
        n("cloud", NodeType.CLOUD, 3),
    ]
    traffic = [TrafficSpec("iot", "cloud", packet_size_bytes=100,
                           schedule_s=(0, 0.01))]
    result = SimulationEngine(cfg, nodes, traffic).run()
    assert result.metrics.delivered == 2
    assert result.fog_statistics["fog"]["mean_queue_wait_s"] > 0


def test_topology_is_recomputed_and_link_down_is_recorded():
    cfg = SimulationConfig(duration_s=0.5, topology_update_interval_s=0.25,
                           satellite_ground_range_km=500)
    nodes = [
        n("sat", NodeType.SATELLITE, 7000, orbital_period_s=1.0),
        n("gs", NodeType.GROUND_STATION, 7000, 0),
    ]
    result = SimulationEngine(cfg, nodes, []).run()
    down = [e for e in result.events if e.event_type == "link_down"]
    assert len(down) == 1
    assert down[0].timestamp_s == pytest.approx(0.25)
    assert result.topology_statistics["links"] == 0


def test_node_failure_and_recovery_are_scheduled_in_virtual_time():
    cfg = SimulationConfig(duration_s=3, topology_update_interval_s=1,
                           iot_ground_range_km=5)
    failures = [
        FailureSchedule(1, "node_failure", node_id="gs"),
        FailureSchedule(2, "node_recovery", node_id="gs"),
    ]
    result = SimulationEngine(
        cfg, [n("iot", NodeType.IOT, 0), n("gs", NodeType.GROUND_STATION, 1)], [],
        failures=failures,
    ).run()
    states = [(e.event_type, e.timestamp_s) for e in result.events
              if e.event_type in {"node_failure", "node_recovery"}]
    assert states == [("node_failure", 1), ("node_recovery", 2)]
    assert result.topology_statistics["operational_nodes"] == 2


def test_empty_run_has_safe_metric_denominators():
    engine = _direct_sim(duration=1)
    engine.traffic = []
    result = engine.run()
    assert result.metrics.generated == 0
    assert result.metrics.packet_delivery_ratio == 0
    assert result.metrics.throughput_bps == 0
    assert result.metrics.mean_latency_s is None
    assert result.metrics.p95_latency_s is None
