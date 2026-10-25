"""Structured simulation events, route decisions, and failure schedules."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FailureSchedule:
    """A deterministic timestamped topology or link-condition action.

    ``event_type`` is one of ``link_failure``, ``link_recovery``,
    ``node_failure``, ``node_recovery``, ``fog_overload``,
    ``fog_recovery``, ``congestion_change``, or ``packet_loss_change``. Link actions use ``source``
    and ``target``. Node actions use ``node_id``. Congestion changes also use
    source/target and a normalized ``value`` in [0, 1].
    """

    time_s: float
    event_type: str
    node_id: str | None = None
    source: str | None = None
    target: str | None = None
    value: float | None = None
    description: str = ""

    def __post_init__(self) -> None:
        supported = {
            "link_failure", "link_recovery", "node_failure", "node_recovery",
            "fog_overload", "fog_recovery", "congestion_change", "packet_loss_change",
        }
        if self.time_s < 0 or self.event_type not in supported:
            raise ValueError("invalid failure schedule time or event_type")
        if self.event_type.startswith("link_") or self.event_type in {
            "congestion_change", "packet_loss_change"
        }:
            if not self.source or not self.target:
                raise ValueError(f"{self.event_type} requires source and target")
        else:
            if not self.node_id:
                raise ValueError(f"{self.event_type} requires node_id")
        if self.event_type in {"congestion_change", "packet_loss_change"} and (
            self.value is None or not 0.0 <= self.value <= 1.0
        ):
            raise ValueError(f"{self.event_type} requires value in [0, 1]")


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    event_id: str
    timestamp_s: float
    event_type: str
    affected_node: str | None = None
    source: str | None = None
    target: str | None = None
    packet_id: str | None = None
    description: str = ""
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    timestamp_s: float
    packet_id: str
    algorithm: str
    source: str
    destination: str
    path: tuple[str, ...]
    available: bool
    cause: str
    route_cost: float
    estimated_latency_ms: float
    failure_detection_s: float | None = None
    recovery_time_s: float | None = None
