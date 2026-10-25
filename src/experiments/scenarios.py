from __future__ import annotations

import math
from dataclasses import dataclass

from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Position
from src.simulation.events import FailureSchedule
from src.traffic import TrafficSpec


@dataclass(frozen=True)
class ExperimentConfig:
    scenario: str = "stable_topology"
    seeds: tuple[int, ...] = (7, 17, 27)
    duration_s: float = 2.0
    satellite_count: int = 3
    traffic_intensity: float = 10.0
    algorithms: tuple[str, ...] = ("shortest_latency", "multi_factor")
    output_dir: str = "experiment_output"
    storage: str = "local"

    def __post_init__(self):
        if self.scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {self.scenario!r}; choose from {sorted(SCENARIOS)}")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be a non-empty tuple of unique integers")
        if self.duration_s <= 0 or self.satellite_count < 2 or self.traffic_intensity <= 0:
            raise ValueError("duration, traffic intensity, and satellite_count (>=2) must be positive")
        if not self.algorithms or any(a not in {"shortest_latency", "multi_factor"} for a in self.algorithms):
            raise ValueError("algorithms must contain shortest_latency and/or multi_factor")
        if self.storage not in {"local", "postgres"}:
            raise ValueError("storage must be local or postgres")


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    description: str

    def build(self, seed: int, duration_s: float, satellite_count: int,
              traffic_intensity: float):
        period = 1e12 if self.name == "stable_topology" else 1200.0
        config = SimulationConfig(seed=seed, duration_s=duration_s,
            topology_update_interval_s=min(1.0, duration_s), satellite_range_km=2500,
            satellite_ground_range_km=2200, iot_ground_range_km=20,
            iot_satellite_range_km=1500, ground_fog_range_km=150,
            fog_cloud_range_km=1000, packet_timeout_s=max(0.2, duration_s * 0.8),
            route_computation_delay_ms=1, max_generated_packets=50000)
        nodes = [Node("iot-0", NodeType.IOT, Position(7000, 0))]
        # Nearly collocated satellites provide genuine, range-eligible ISLs.
        for i in range(satellite_count):
            phase = (i - (satellite_count - 1) / 2) * 0.006
            nodes.append(Node(f"sat-{i}", NodeType.SATELLITE,
                Position(7000 * math.cos(phase), 7000 * math.sin(phase)),
                orbital_period_s=period, initial_orbital_phase_rad=phase))
        nodes.extend([
            Node("gs-0", NodeType.GROUND_STATION, Position(7000, 900)),
            Node("fog-0", NodeType.FOG, Position(7000, 901), processing_capacity_pps=1000,
                 processing_delay_ms=1),
            Node("cloud-0", NodeType.CLOUD, Position(7000, 902)),
        ])
        rate = traffic_intensity * (8 if self.name == "high_traffic_load" else 1)
        traffic = [TrafficSpec("iot-0", "cloud-0", rate_pps=rate,
                               packet_size_bytes=512, priority="medium")]
        t = min(duration_s * 0.25, max(0.02, duration_s * 0.1))
        if t >= duration_s:
            t = duration_s / 2
        failures = []
        if self.name == "inter_satellite_link_failure":
            failures = [FailureSchedule(t, "link_failure", source="sat-0", target="sat-1")]
        elif self.name == "satellite_node_failure":
            failures = [FailureSchedule(t, "node_failure", node_id="sat-0")]
        elif self.name == "congestion_spike":
            failures = [FailureSchedule(t, "congestion_change", source="gs-0", target="fog-0", value=0.95)]
        elif self.name == "fog_node_overload":
            failures = [FailureSchedule(t, "fog_overload", node_id="fog-0")]
        elif self.name == "multiple_simultaneous_failures":
            failures = [FailureSchedule(t, "link_failure", source="sat-0", target="sat-1"),
                        FailureSchedule(t, "node_failure", node_id=f"sat-{satellite_count - 1}")]
        return config, nodes, traffic, failures


SCENARIOS = {
    name: ScenarioDefinition(name, description) for name, description in {
        "stable_topology": "Long-period satellite configuration with no scheduled failure.",
        "normal_satellite_mobility": "Slow deterministic circular satellite motion.",
        "inter_satellite_link_failure": "A physically eligible inter-satellite link fails.",
        "satellite_node_failure": "An operational satellite node fails.",
        "congestion_spike": "Congestion rises on the active ground-to-fog link.",
        "fog_node_overload": "The fog node becomes unavailable at the scheduled time.",
        "high_traffic_load": "Traffic rate is increased eightfold over configured intensity.",
        "multiple_simultaneous_failures": "An ISL and a satellite fail at the same time.",
    }.items()
}
