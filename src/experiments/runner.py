from __future__ import annotations

import time
import uuid
from dataclasses import asdict

from src.experiments.scenarios import ExperimentConfig, SCENARIOS
from src.routing import RoutingMode
from src.simulation import SimulationEngine


def metrics_from_result(result):
    m = result.metrics
    attempts = sum(v.get("transmissions", 0) for v in result.link_statistics.values())
    losses = sum(v.get("lost_frames", 0) for v in result.link_statistics.values())
    fog = list(result.fog_statistics.values())
    delivered = m.delivered
    return {
        "generated_packets": m.generated, "delivered_packets": m.delivered,
        "dropped_packets": m.dropped, "timed_out_packets": m.timed_out,
        "pending_packets": m.pending, "mean_latency_ms": None if m.mean_latency_s is None else m.mean_latency_s * 1000,
        "median_latency_ms": None if m.median_latency_s is None else m.median_latency_s * 1000,
        "p95_latency_ms": None if m.p95_latency_s is None else m.p95_latency_s * 1000,
        "pdr": m.packet_delivery_ratio,
        "effective_throughput_mbps": m.throughput_bps / 1_000_000,
        "reroutes": m.reroutes, "reroutes_per_delivered_packet": m.reroutes / delivered if delivered else None,
        "mean_hop_count": m.hop_count_mean, "recovery_successes": m.recovery_successes,
        "recovery_failures": m.recovery_failures,
        "mean_recovery_time_ms": None if m.mean_recovery_time_s is None else m.mean_recovery_time_s * 1000,
        "recovery_sample_count": len(result.route_recovery_times_s),
        "packet_loss_rate": losses / attempts if attempts else None,
        "drop_rate": m.dropped / m.generated if m.generated else None,
        "timeout_rate": m.timed_out / m.generated if m.generated else None,
        "mean_fog_utilization": sum(x["utilization"] for x in fog) / len(fog) if fog else None,
        "mean_fog_queue_delay_ms": (sum(x["mean_queue_wait_s"] for x in fog) / len(fog) * 1000) if fog else None,
        "congestion_events": sum(e.event_type == "congestion_change" for e in result.events),
        "wall_clock_runtime_s": result.wall_clock_runtime_s,
        "route_computation_time_ms": None,
        "active_link_availability": None,
        "notes": "Latency includes serialization, configured overhead, propagation, fog queue/service, route computation and rerouting delays. PDR denominator is all generated packets including pending; window is full duration. Packet loss is lost frames/transmission attempts. Route-computation CPU time and time-integrated link availability are not instrumented.",
    }


class ExperimentRunner:
    def __init__(self, config: ExperimentConfig, repository=None):
        self.config = config
        self.repository = repository

    def run(self):
        experiment_id = f"exp-{uuid.uuid4().hex}"
        scenario = SCENARIOS[self.config.scenario]
        snapshot = {"parameters": asdict(self.config), "scenario_definition": scenario.description,
                    "metric_definitions": metric_definitions()}
        started = time.perf_counter()
        if self.repository is not None and hasattr(self.repository, "create_experiment"):
            self.repository.create_experiment(experiment_id, snapshot)
        rows = []
        for seed in self.config.seeds:
            for algorithm in self.config.algorithms:
                run_id = f"{experiment_id}-{self.config.scenario}-{algorithm}-{seed}"
                base = {"experiment_id": experiment_id, "run_id": run_id,
                        "scenario": self.config.scenario, "algorithm": algorithm,
                        "seed": seed, "duration_s": self.config.duration_s,
                        "traffic_intensity_pps": self.config.traffic_intensity,
                        "satellite_count": self.config.satellite_count,
                        "configuration": snapshot, "status": "failed", "error": None,
                        "expected_event_applied": None, "event_schedule": []}
                try:
                    sim_config, nodes, traffic, failures = scenario.build(seed,
                        self.config.duration_s, self.config.satellite_count,
                        self.config.traffic_intensity)
                    base["event_schedule"] = [asdict(f) for f in failures]
                    base["traffic_parameters"] = [{"source": t.source, "destination": t.destination,
                        "rate_pps": t.rate_pps, "packet_size_bytes": t.packet_size_bytes,
                        "priority": t.priority, "schedule_s": t.schedule_s} for t in traffic]
                    base["traffic_rate_effective_pps"] = traffic[0].rate_pps if traffic else None
                    base["topology_parameters"] = {"satellite_range_km": sim_config.satellite_range_km,
                        "satellite_ground_range_km": sim_config.satellite_ground_range_km,
                        "iot_satellite_range_km": sim_config.iot_satellite_range_km,
                        "ground_fog_range_km": sim_config.ground_fog_range_km,
                        "topology_update_interval_s": sim_config.topology_update_interval_s,
                        "satellite_count": self.config.satellite_count}
                    engine = SimulationEngine(sim_config, nodes, traffic,
                        routing_mode=RoutingMode(algorithm), failures=failures,
                        run_id=run_id, repository=self.repository)
                    result = engine.run()
                    metrics = metrics_from_result(result)
                    expected = {"inter_satellite_link_failure": {"link_failure"},
                                "satellite_node_failure": {"node_failure"},
                                "congestion_spike": {"congestion_change"},
                                "fog_node_overload": {"fog_overload"},
                                "multiple_simultaneous_failures": {"link_failure", "node_failure"}}.get(self.config.scenario)
                    applied = None if expected is None else expected <= {e.event_type for e in result.events}
                    base.update(status="completed", metrics=metrics,
                                expected_event_applied=applied,
                                event_schedule=[asdict(f) for f in failures])
                    if applied is False:
                        base["notes"] = "Scheduled event did not produce a matching emitted simulation event."
                except Exception as exc:
                    base["error"] = f"{type(exc).__name__}: {exc}"
                if self.repository is not None and hasattr(self.repository, "record_experiment_run"):
                    self.repository.record_experiment_run(experiment_id, base)
                rows.append(base)
        elapsed = time.perf_counter() - started
        result_bundle = {"experiment_id": experiment_id, "scenario": self.config.scenario,
            "definition": scenario.description, "configuration": snapshot,
            "metric_definitions": metric_definitions(), "rows": rows,
            "wall_clock_duration_s": elapsed,
            "status": "completed" if all(r["status"] == "completed" for r in rows) else "completed_with_failures",
            "storage": getattr(self.repository, "backend", "local_export_only")}
        if self.repository is not None and hasattr(self.repository, "finish_experiment"):
            self.repository.finish_experiment(experiment_id, result_bundle["status"], elapsed)
        return result_bundle


def metric_definitions():
    return {"mean_latency_ms": "mean delivered packet latency, milliseconds",
        "median_latency_ms": "median delivered packet latency, milliseconds",
        "p95_latency_ms": "nearest-rank p95, only when at least 20 deliveries, milliseconds",
        "pdr": "delivered/generated packets; pending remain in generated denominator",
        "effective_throughput_mbps": "delivered payload bits/full observation window, decimal Mbps",
        "mean_recovery_time_ms": "mean successful detection-to-valid-route time, milliseconds",
        "packet_loss_rate": "lost frames/transmission attempts",
        "drop_rate": "dropped/generated packets", "timeout_rate": "timed out/generated packets",
        "mean_hop_count": "mean hops over delivered packets", "wall_clock_runtime_s": "simulation execution time, seconds",
        "route_computation_time_ms": "unavailable: CPU computation duration is not instrumented",
        "active_link_availability": "unavailable: time-integrated availability is not instrumented"}
