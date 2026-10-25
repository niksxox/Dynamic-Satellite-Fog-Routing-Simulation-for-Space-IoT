from src.experiments.reporting import export_experiment
from src.experiments.runner import ExperimentRunner
from src.experiments.scenarios import ExperimentConfig
from src.experiments.scenarios import SCENARIOS
from src.simulation import SimulationEngine


def test_small_complete_paired_experiment_exports_actual_results(tmp_path):
    config = ExperimentConfig(scenario="stable_topology", seeds=(3,), duration_s=0.5,
        satellite_count=2, traffic_intensity=80.0, output_dir=str(tmp_path))
    bundle = ExperimentRunner(config).run()
    exported = export_experiment(bundle, tmp_path)
    assert len(exported["rows"]) == 2
    assert {r["algorithm"] for r in exported["rows"]} == {"shortest_latency", "multi_factor"}
    assert all(r["status"] == "completed" for r in exported["rows"])
    assert all(r["metrics"]["generated_packets"] > 0 for r in exported["rows"])
    assert list(tmp_path.glob("*.csv"))
    assert list(tmp_path.glob("*.json"))
    assert list(tmp_path.glob("*_report.md"))


def test_fixed_seed_reproduces_packet_outcomes():
    outputs = []
    for suffix in ("a", "b"):
        config, nodes, traffic, failures = SCENARIOS["normal_satellite_mobility"].build(31, 1.0, 3, 30.0)
        result = SimulationEngine(config, nodes, traffic, failures=failures,
                                  run_id=f"repro-{suffix}").run()
        outputs.append((result.metrics, [(p.generated_at_s, p.state.value, tuple(p.path)) for p in result.packets]))
    assert outputs[0] == outputs[1]
