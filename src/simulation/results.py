"""Structured in-memory output from one simulation run."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.metrics.collector import MetricsSummary
from src.models.config import SimulationConfig
from src.models.network import Packet
from src.simulation.events import RoutingDecision, SimulationEvent


@dataclass(slots=True)
class SimulationResults:
    run_id: str
    config: SimulationConfig
    routing_mode: str
    start_time_s: float
    end_time_s: float
    wall_clock_runtime_s: float = 0.0
    packets: list[Packet] = field(default_factory=list)
    events: list[SimulationEvent] = field(default_factory=list)
    routing_decisions: list[RoutingDecision] = field(default_factory=list)
    route_recovery_times_s: list[float] = field(default_factory=list)
    route_recovery_failures: int = 0
    link_statistics: dict[str, dict[str, float]] = field(default_factory=dict)
    fog_statistics: dict[str, dict[str, float]] = field(default_factory=dict)
    topology_statistics: dict[str, int] = field(default_factory=dict)
    per_node_statistics: dict[str, dict[str, float]] = field(default_factory=dict)
    events_truncated: bool = False
    metrics: MetricsSummary | None = None
    node_configurations: list[object] = field(default_factory=list)
    initial_link_configurations: list[tuple[str, str, dict]] = field(default_factory=list)
    current_link_configurations: list[tuple[str, str, dict]] = field(default_factory=list)

    @property
    def delivered_packets(self) -> list[Packet]:
        from src.models.network import PacketState
        return [p for p in self.packets if p.state is PacketState.DELIVERED]

    @property
    def pending_packets(self) -> list[Packet]:
        from src.models.network import PacketState
        return [p for p in self.packets if p.state is PacketState.PENDING]
