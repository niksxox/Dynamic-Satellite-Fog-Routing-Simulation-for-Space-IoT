from __future__ import annotations

import uuid

from src.experiments.runner import ExperimentRunner
from src.experiments.scenarios import ExperimentConfig, SCENARIOS
from src.routing import RoutingMode
from src.simulation import SimulationEngine


def run_simulation(scenario_name: str, algorithm: str, seed: int, duration_s: float,
                   satellite_count: int, traffic_intensity: float, repository=None):
    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}")
    if algorithm not in {"shortest_latency", "multi_factor"}:
        raise ValueError(f"Unknown algorithm: {algorithm}")
    if seed < 0 or duration_s <= 0 or satellite_count < 2 or traffic_intensity <= 0:
        raise ValueError("Seed must be nonnegative; duration and traffic must be positive; use at least 2 satellites.")
    config, nodes, traffic, failures = SCENARIOS[scenario_name].build(
        seed, duration_s, satellite_count, traffic_intensity)
    run_id = f"dashboard-{uuid.uuid4().hex}"
    result = SimulationEngine(config, nodes, traffic, routing_mode=RoutingMode(algorithm),
        failures=failures, run_id=run_id, repository=repository).run()
    expected = {"inter_satellite_link_failure": {"link_failure"},
                "satellite_node_failure": {"node_failure"},
                "congestion_spike": {"congestion_change"},
                "fog_node_overload": {"fog_overload"},
                "multiple_simultaneous_failures": {"link_failure", "node_failure"}}.get(scenario_name)
    applied = None if expected is None else expected <= {event.event_type for event in result.events}
    return result, {"scenario": scenario_name, "algorithm": algorithm, "seed": seed,
        "duration_s": duration_s, "satellite_count": satellite_count,
        "traffic_intensity_pps": traffic[0].rate_pps if traffic else None,
        "failure_schedule": failures, "expected_event_applied": applied}


def run_paired_experiment(scenario: str, algorithm: str, seed: int, duration_s: float,
                          satellite_count: int, traffic_intensity: float, output_dir: str,
                          repository=None):
    algorithms = ("shortest_latency", "multi_factor") if algorithm == "both" else (algorithm,)
    config = ExperimentConfig(scenario=scenario, seeds=(seed,), duration_s=duration_s,
        satellite_count=satellite_count, traffic_intensity=traffic_intensity,
        algorithms=algorithms, output_dir=output_dir,
        storage="postgres" if repository else "local")
    return ExperimentRunner(config, repository).run()
