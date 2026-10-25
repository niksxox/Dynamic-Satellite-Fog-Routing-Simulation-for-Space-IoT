from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, CheckConstraint, DateTime, Float, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, JSON, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    run_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    simulation_start_s: Mapped[float] = mapped_column(Float, default=0.0)
    simulation_end_s: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    routing_algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), default="phase-4")
    error_summary: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("status in ('running','completed','failed')", name="ck_run_status"),)


class NetworkNode(Base):
    __tablename__ = "network_nodes"
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id", ondelete="CASCADE"), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)


class SatelliteConfig(Base):
    __tablename__ = "satellites"
    run_id: Mapped[str] = mapped_column(primary_key=True)
    satellite_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    orbital_parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    operational_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (ForeignKeyConstraint(["run_id", "satellite_id"], ["network_nodes.run_id", "network_nodes.node_id"], ondelete="CASCADE"),)


class IoTDeviceConfig(Base):
    __tablename__ = "iot_devices"
    run_id: Mapped[str] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    traffic_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    operational_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (ForeignKeyConstraint(["run_id", "device_id"], ["network_nodes.run_id", "network_nodes.node_id"], ondelete="CASCADE"),)


class FogNodeConfig(Base):
    __tablename__ = "fog_nodes"
    run_id: Mapped[str] = mapped_column(primary_key=True)
    fog_node_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    processing_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    operational_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (ForeignKeyConstraint(["run_id", "fog_node_id"], ["network_nodes.run_id", "network_nodes.node_id"], ondelete="CASCADE"),)


class LinkConfig(Base):
    __tablename__ = "links"
    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    target: Mapped[str] = mapped_column(String(160), nullable=False)
    link_type: Mapped[str] = mapped_column(String(80), nullable=False)
    bandwidth_mbps: Mapped[float] = mapped_column(Float, nullable=False)
    packet_loss_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    operational: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    __table_args__ = (
        ForeignKeyConstraint(["run_id"], ["simulation_runs.run_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["run_id", "source"], ["network_nodes.run_id", "network_nodes.node_id"]),
        ForeignKeyConstraint(["run_id", "target"], ["network_nodes.run_id", "network_nodes.node_id"]),
        UniqueConstraint("run_id", "source", "target", name="uq_run_link"),
    )


class PacketRecord(Base):
    __tablename__ = "packets"
    run_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    packet_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    destination: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at_s: Mapped[float] = mapped_column(Float, nullable=False)
    final_state: Mapped[str] = mapped_column(String(16), nullable=False)
    delivered_at_s: Mapped[float | None] = mapped_column(Float)
    latency_s: Mapped[float | None] = mapped_column(Float)
    hop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reroute_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    final_path: Mapped[list] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["run_id"], ["simulation_runs.run_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["run_id", "source"], ["network_nodes.run_id", "network_nodes.node_id"]),
        ForeignKeyConstraint(["run_id", "destination"], ["network_nodes.run_id", "network_nodes.node_id"]),
        CheckConstraint("final_state in ('delivered','dropped','timed_out','pending')", name="ck_packet_state"),
        CheckConstraint("(final_state = 'delivered') = (delivered_at_s IS NOT NULL)", name="ck_packet_delivery_time"),
        Index("ix_packets_packet_id", "packet_id"),
    )


class RouteRecord(Base):
    __tablename__ = "routes"
    route_record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False)
    packet_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    destination: Mapped[str] = mapped_column(String(160), nullable=False)
    path: Mapped[list] = mapped_column(JSON, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    route_cost: Mapped[float | None] = mapped_column(Float)
    estimated_latency_ms: Mapped[float | None] = mapped_column(Float)
    bottleneck_bandwidth_mbps: Mapped[float | None] = mapped_column(Float)
    selected_at_s: Mapped[float] = mapped_column(Float, nullable=False)
    cause: Mapped[str] = mapped_column(String(80), nullable=False)
    failure_detection_s: Mapped[float | None] = mapped_column(Float)
    recovery_time_s: Mapped[float | None] = mapped_column(Float)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "packet_id"], ["packets.run_id", "packets.packet_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["run_id", "source"], ["network_nodes.run_id", "network_nodes.node_id"]),
        ForeignKeyConstraint(["run_id", "destination"], ["network_nodes.run_id", "network_nodes.node_id"]),
        Index("ix_routes_packet", "run_id", "packet_id", "selected_at_s"),
    )


class SimulationEventRecord(Base):
    __tablename__ = "simulation_events"
    run_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    timestamp_s: Mapped[float] = mapped_column(Float, nullable=False)
    affected_node: Mapped[str | None] = mapped_column(String(160))
    source: Mapped[str | None] = mapped_column(String(160))
    target: Mapped[str | None] = mapped_column(String(160))
    packet_id: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["run_id"], ["simulation_runs.run_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["run_id", "packet_id"], ["packets.run_id", "packets.packet_id"]),
        Index("ix_events_type_time", "run_id", "event_type", "timestamp_s"),
    )


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    metric_snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id", ondelete="CASCADE"), nullable=False)
    timestamp_s: Mapped[float] = mapped_column(Float, nullable=False)
    generated: Mapped[int] = mapped_column(Integer, nullable=False)
    delivered: Mapped[int] = mapped_column(Integer, nullable=False)
    dropped: Mapped[int] = mapped_column(Integer, nullable=False)
    timed_out: Mapped[int] = mapped_column(Integer, nullable=False)
    pending: Mapped[int] = mapped_column(Integer, nullable=False)
    pdr: Mapped[float | None] = mapped_column(Float)
    throughput_bps: Mapped[float | None] = mapped_column(Float)
    mean_latency_s: Mapped[float | None] = mapped_column(Float)
    median_latency_s: Mapped[float | None] = mapped_column(Float)
    p95_latency_s: Mapped[float | None] = mapped_column(Float)
    reroutes: Mapped[int] = mapped_column(Integer, nullable=False)
    recovery_successes: Mapped[int] = mapped_column(Integer, nullable=False)
    recovery_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    active_nodes: Mapped[int] = mapped_column(Integer, nullable=False)
    active_links: Mapped[int] = mapped_column(Integer, nullable=False)
    fog_statistics: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("run_id", "timestamp_s", name="uq_metric_run_time"),
                      Index("ix_metrics_run_time", "run_id", "timestamp_s"))


class ExperimentRecord(Base):
    __tablename__ = "experiments"
    experiment_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wall_clock_duration_s: Mapped[float | None] = mapped_column(Float)


class ExperimentRunRecord(Base):
    __tablename__ = "experiment_runs"
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.experiment_id", ondelete="CASCADE"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id", ondelete="SET NULL"), primary_key=True)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_experiment_runs_scenario_algo", "scenario", "algorithm", "seed"),)
