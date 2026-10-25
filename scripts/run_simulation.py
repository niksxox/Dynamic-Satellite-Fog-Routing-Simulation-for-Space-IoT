"""Run the deterministic sat-A failure and rerouting example headlessly."""

from __future__ import annotations

import argparse
import json
import math

from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Position
from src.simulation import FailureSchedule, SimulationEngine
from src.traffic import TrafficSpec


def build_demo(seed: int, duration_s: float) -> SimulationEngine:
    """Build the physically range-eligible two-satellite demonstration."""
    config = SimulationConfig(
        seed=seed,
        duration_s=duration_s,
        packet_timeout_s=min(10.0, max(0.1, duration_s / 2)),
        topology_update_interval_s=min(5.0, duration_s / 2),
        iot_ground_range_km=20,
        route_computation_delay_ms=1,
    )
    nodes = [
        Node("iot", NodeType.IOT, Position(7000, -500)),
        Node("sat-a", NodeType.SATELLITE, Position(7000, 0), orbital_period_s=100_000),
        Node("sat-b", NodeType.SATELLITE, Position(6900, 100), orbital_period_s=100_000,
             initial_orbital_phase_rad=math.atan2(100, 6900)),
        Node("gs", NodeType.GROUND_STATION, Position(7000, 1000)),
        Node("fog", NodeType.FOG, Position(7000, 1001), processing_capacity_pps=1000),
        Node("cloud", NodeType.CLOUD, Position(7000, 1002)),
    ]
    packets = tuple(t for t in (0.0, 0.02, 0.04) if t < duration_s)
    traffic = [TrafficSpec("iot", "cloud", packet_size_bytes=512,
                           priority="medium", schedule_s=packets)]
    failure_time = 0.0017
    failures = [FailureSchedule(failure_time, "link_failure", source="sat-a", target="gs")]
    return SimulationEngine(config, nodes, traffic, failures=failures, run_id="reroute-demo")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--duration", type=float, default=0.2,
                        help="virtual simulation duration in seconds (must exceed 1.7ms)")
    args = parser.parse_args()
    if args.duration <= 0.0017:
        parser.error("--duration must exceed 0.0017 seconds for the scheduled failure")
    result = build_demo(args.seed, args.duration).run()
    summary = result.metrics
    print(json.dumps({
        "run_id": result.run_id,
        "routing_mode": result.routing_mode,
        "seed": result.config.seed,
        "simulation_time_s": result.end_time_s,
        "generated": summary.generated,
        "delivered": summary.delivered,
        "dropped": summary.dropped,
        "timed_out": summary.timed_out,
        "pending": summary.pending,
        "pdr": summary.packet_delivery_ratio,
        "mean_latency_s": summary.mean_latency_s,
        "reroutes": summary.reroutes,
        "recovery_times_s": result.route_recovery_times_s,
        "events_truncated": result.events_truncated,
    }, indent=2))


if __name__ == "__main__":
    main()
