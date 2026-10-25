from src.experiments.scenarios import SCENARIOS
from src.routing import RoutingMode
from src.simulation import SimulationEngine


def _run(name):
    config, nodes, traffic, failures = SCENARIOS[name].build(19, 600, 3, 0.1)
    result = SimulationEngine(config, nodes, traffic,
        routing_mode=RoutingMode("shortest_latency"), failures=failures).run()
    return result, failures


def test_orbital_visibility_demo_changes_topology_without_injected_failures():
    result, failures = _run("orbital_visibility_demo")
    assert failures == []
    transitions = [e for e in result.events if e.event_type.startswith("link_geometrically_")]
    assert transitions
    assert any(e.event_type == "link_geometrically_unavailable" for e in transitions)


def test_orbital_motion_and_scheduled_failure_are_both_recorded():
    result, failures = _run("orbital_motion_with_link_failure")
    assert any(f.event_type == "link_failure" for f in failures)
    event_types = {event.event_type for event in result.events}
    assert "link_failure" in event_types
    assert "link_geometrically_unavailable" in event_types
    assert "link_geometrically_available" in event_types
