from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.database.engine import Database, create_database
from src.database.models import (FogNodeConfig, IoTDeviceConfig, LinkConfig, MetricSnapshot,
    NetworkNode, PacketRecord, RouteRecord, SatelliteConfig, SimulationEventRecord,
    SimulationRun)
from src.database.session import session_scope


class DuplicateRunError(ValueError):
    pass


def _add_in_batches(session, records, batch_size=1000):
    for offset in range(0, len(records), batch_size):
        session.add_all(records[offset:offset + batch_size])
        session.flush()


def _json(value):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


class PostgresSimulationRepository:
    backend = "postgresql"

    def __init__(self, database: Database):
        self.database = database

    def close(self):
        self.database.dispose()

    def create_run(self, run_id, config, algorithm, seed, duration_s, model_version="phase-4"):
        with session_scope(self.database.session_factory) as s:
            if s.get(SimulationRun, run_id) is not None:
                raise DuplicateRunError(f"run_id {run_id!r} already exists; run IDs are immutable")
            s.add(SimulationRun(run_id=run_id, status="running", routing_algorithm=algorithm,
                random_seed=seed, duration_s=duration_s, configuration=_json(config),
                model_version=model_version))

    def save_network_configuration(self, run_id, nodes, edges):
        node_models, subtype_models = [], []
        for n in nodes:
            typ = n.node_type.value
            cfg = {k: _json(v) for k, v in asdict(n).items()}
            node_models.append(NetworkNode(run_id=run_id, node_id=n.node_id,
                                           node_type=typ, configuration=cfg))
            if typ == "satellite":
                subtype_models.append(SatelliteConfig(run_id=run_id, satellite_id=n.node_id,
                    orbital_parameters={k: cfg[k] for k in ("orbital_plane", "initial_orbital_phase_rad", "orbital_period_s", "position")},
                    operational_config={"operational": n.operational, "communication_range_km": n.communication_range_km, "bandwidth_mbps": n.bandwidth_mbps}))
            elif typ == "iot":
                subtype_models.append(IoTDeviceConfig(run_id=run_id, device_id=n.node_id,
                    traffic_config={k: cfg[k] for k in ("packet_generation_rate_pps", "default_packet_size_bytes", "traffic_priority", "destination")},
                    operational_config={"operational": n.operational, "position": cfg["position"]}))
            elif typ == "fog":
                subtype_models.append(FogNodeConfig(run_id=run_id, fog_node_id=n.node_id,
                    processing_config={k: cfg[k] for k in ("processing_capacity_pps", "processing_delay_ms", "queue_length", "utilization")},
                    operational_config={"operational": n.operational, "position": cfg["position"]}))
        links = []
        for source, target, attrs in edges:
            stable = "-".join(sorted((source, target)))
            lid = hashlib.sha256(f"{run_id}:{stable}".encode()).hexdigest()
            links.append(LinkConfig(link_id=lid, run_id=run_id, source=source, target=target,
                link_type="<->".join(sorted((attrs.get("source_type", "node"), attrs.get("target_type", "node")))),
                bandwidth_mbps=float(attrs["bandwidth_mbps"]),
                packet_loss_probability=float(attrs.get("packet_loss_probability", 0)),
                operational=bool(attrs.get("operational", True)), configuration=_json(attrs)))
        with session_scope(self.database.session_factory) as s:
            _add_in_batches(s, node_models)
            _add_in_batches(s, subtype_models)
            _add_in_batches(s, links)

    def persist_results(self, results):
        m = results.metrics
        packets = [PacketRecord(run_id=results.run_id, packet_id=p.packet_id, source=p.source,
            destination=p.destination, size_bytes=p.size_bytes, generated_at_s=p.generated_at_s,
            final_state=p.state.value, delivered_at_s=p.delivered_at_s, latency_s=p.latency_s,
            hop_count=p.hop_count, reroute_count=p.reroute_count, reason=p.drop_reason,
            final_path=list(p.path)) for p in results.packets]
        with session_scope(self.database.session_factory) as s:
            run = s.get(SimulationRun, results.run_id)
            if run is None or run.status != "running":
                raise ValueError("results can only be persisted once for an existing running run")
            for source, target, attrs in results.current_link_configurations:
                link = s.scalar(select(LinkConfig).where(LinkConfig.run_id == results.run_id,
                    LinkConfig.source == source, LinkConfig.target == target))
                if link is not None:
                    link.operational = bool(attrs.get("operational", True))
                    link.bandwidth_mbps = float(attrs.get("bandwidth_mbps", link.bandwidth_mbps))
                    link.packet_loss_probability = float(attrs.get("packet_loss_probability", 0.0))
                    link.configuration = _json(attrs)
            _add_in_batches(s, packets)
            routes = [RouteRecord(run_id=results.run_id, packet_id=d.packet_id,
                source=d.source, destination=d.destination, path=list(d.path), algorithm=d.algorithm,
                route_cost=d.route_cost, estimated_latency_ms=d.estimated_latency_ms,
                bottleneck_bandwidth_mbps=None, selected_at_s=d.timestamp_s, cause=d.cause,
                failure_detection_s=d.failure_detection_s, recovery_time_s=d.recovery_time_s,
                available=d.available) for d in results.routing_decisions]
            events = [SimulationEventRecord(run_id=results.run_id, event_id=e.event_id,
                event_type=e.event_type, timestamp_s=e.timestamp_s, affected_node=e.affected_node,
                source=e.source, target=e.target, packet_id=e.packet_id,
                description=e.description, metadata_json=_json(e.details)) for e in results.events]
            _add_in_batches(s, routes)
            _add_in_batches(s, events)
            s.add(MetricSnapshot(run_id=results.run_id, timestamp_s=results.end_time_s,
                generated=m.generated, delivered=m.delivered, dropped=m.dropped,
                timed_out=m.timed_out, pending=m.pending, pdr=m.packet_delivery_ratio,
                throughput_bps=m.throughput_bps, mean_latency_s=m.mean_latency_s,
                median_latency_s=m.median_latency_s, p95_latency_s=m.p95_latency_s,
                reroutes=m.reroutes, recovery_successes=m.recovery_successes,
                recovery_failures=m.recovery_failures,
                active_nodes=sum(n.operational for n in results.node_configurations),
                active_links=sum(bool(attrs.get("operational", True)) for _, _, attrs in results.current_link_configurations),
                fog_statistics=_json(results.fog_statistics)))
            run.status = "completed"
            run.ended_at = datetime.now(timezone.utc)
            run.simulation_end_s = results.end_time_s

    def mark_failed(self, run_id, error):
        with session_scope(self.database.session_factory) as s:
            run = s.get(SimulationRun, run_id)
            if run is not None and run.status == "running":
                run.status = "failed"
                run.error_summary = str(error)[:4000]
                run.ended_at = datetime.now(timezone.utc)

    def list_runs(self, limit=100):
        with session_scope(self.database.session_factory) as s:
            return [dict(run_id=r.run_id, status=r.status, algorithm=r.routing_algorithm,
                         seed=r.random_seed, duration_s=r.duration_s, configuration=r.configuration)
                    for r in s.scalars(select(SimulationRun).order_by(SimulationRun.created_at.desc()).limit(limit))]

    def get_run_summary(self, run_id):
        with session_scope(self.database.session_factory) as s:
            r = s.get(SimulationRun, run_id)
            if r is None: return None
            metrics = s.scalar(select(MetricSnapshot).where(MetricSnapshot.run_id == run_id))
            return {"run_id": r.run_id, "status": r.status, "algorithm": r.routing_algorithm,
                    "seed": r.random_seed, "duration_s": r.duration_s,
                    "configuration": r.configuration,
                    "metrics": None if metrics is None else {k: getattr(metrics, k) for k in
                    ("generated", "delivered", "dropped", "timed_out", "pending", "pdr", "throughput_bps")}}

    def get_route_history(self, run_id, packet_id):
        with session_scope(self.database.session_factory) as s:
            return list(s.scalars(select(RouteRecord).where(RouteRecord.run_id == run_id,
                RouteRecord.packet_id == packet_id).order_by(RouteRecord.selected_at_s)))

    def get_event_timeline(self, run_id):
        with session_scope(self.database.session_factory) as s:
            return list(s.scalars(select(SimulationEventRecord).where(
                SimulationEventRecord.run_id == run_id).order_by(SimulationEventRecord.timestamp_s)))

    def get_metrics(self, run_id):
        with session_scope(self.database.session_factory) as s:
            return list(s.scalars(select(MetricSnapshot).where(
                MetricSnapshot.run_id == run_id).order_by(MetricSnapshot.timestamp_s)))


class InMemorySimulationRepository:
    """Volatile demo backend; same lifecycle, intentionally no durability."""
    backend = "in_memory_demo"

    def __init__(self): self.runs = {}
    def close(self): pass
    def create_run(self, run_id, config, algorithm, seed, duration_s, model_version="phase-4"):
        if run_id in self.runs: raise DuplicateRunError(f"run_id {run_id!r} already exists")
        self.runs[run_id] = {"status": "running", "algorithm": algorithm, "seed": seed,
            "duration_s": duration_s, "configuration": _json(config), "packets": [], "routes": [],
            "events": [], "metrics": [], "nodes": [], "links": [], "error": None}
    def save_network_configuration(self, run_id, nodes, edges):
        self.runs[run_id]["nodes"] = [_json(n) for n in nodes]
        self.runs[run_id]["links"] = _json(edges)
    def persist_results(self, result):
        r = self.runs[result.run_id]
        if r["status"] != "running" or r["packets"]: raise ValueError("results may be persisted only once")
        r.update(status="completed", packets=list(result.packets), routes=list(result.routing_decisions),
                 events=list(result.events), metrics=[result.metrics])
    def mark_failed(self, run_id, error):
        if run_id in self.runs and self.runs[run_id]["status"] == "running":
            self.runs[run_id].update(status="failed", error=str(error)[:4000])
    def list_runs(self, limit=100): return list(self.runs.values())[-limit:]
    def get_run_summary(self, run_id): return self.runs.get(run_id)
    def get_route_history(self, run_id, packet_id): return [d for d in self.runs[run_id]["routes"] if d.packet_id == packet_id]
    def get_event_timeline(self, run_id): return self.runs[run_id]["events"]
    def get_metrics(self, run_id): return self.runs[run_id]["metrics"]


def create_repository(backend="auto"):
    if backend == "memory": return InMemorySimulationRepository()
    if backend == "postgres": return PostgresSimulationRepository(create_database())
    if backend != "auto": raise ValueError("storage backend must be auto, memory, or postgres")
    import os
    return (PostgresSimulationRepository(create_database()) if os.getenv("DATABASE_URL")
            else InMemorySimulationRepository())
