import pytest

from src.experiments.scenarios import ExperimentConfig, SCENARIOS
from src.topology.engine import TopologyEngine


def test_experiment_config_validates_scenario_seed_and_size():
    with pytest.raises(ValueError):
        ExperimentConfig(scenario="unknown")
    with pytest.raises(ValueError):
        ExperimentConfig(seeds=())
    with pytest.raises(ValueError):
        ExperimentConfig(satellite_count=1)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_required_scenario_topology_builds_with_eligible_primary_route(name):
    config, nodes, traffic, failures = SCENARIOS[name].build(5, 1.0, 3, 10.0)
    topology = TopologyEngine(config)
    graph = topology.initialize_network(nodes)
    assert graph.has_edge("iot-0", "sat-1")
    assert graph.has_edge("sat-0", "sat-1")
    assert graph.has_edge("sat-1", "gs-0")
    assert traffic[0].source == "iot-0"
    assert all(f.time_s <= config.duration_s for f in failures)


def test_paired_builds_are_identical_for_same_scenario_and_seed():
    a = SCENARIOS["inter_satellite_link_failure"].build(17, 1.0, 3, 20.0)
    b = SCENARIOS["inter_satellite_link_failure"].build(17, 1.0, 3, 20.0)
    assert a == b
