"""Core network and packet data structures."""

from dataclasses import dataclass, field
from enum import Enum
import math

from src.orbit.models import GeodeticPosition, OrbitalElements


class NodeType(str, Enum):
    IOT = "iot"
    SATELLITE = "satellite"
    GROUND_STATION = "ground_station"
    FOG = "fog"
    CLOUD = "cloud"


class PacketState(str, Enum):
    GENERATED = "generated"
    WAITING_FOR_ROUTE = "waiting_for_route"
    IN_TRANSIT = "in_transit"
    WAITING_FOR_FOG = "waiting_for_fog"
    DELIVERED = "delivered"
    DROPPED = "dropped"
    TIMED_OUT = "timed_out"
    # A censored observation at the simulation horizon, distinct from a drop.
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class Position:
    """Cartesian position in km. ``frame`` identifies ECEF/ECI when known."""

    x_km: float
    y_km: float
    z_km: float = 0.0
    frame: str = "unspecified"

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.x_km, self.y_km, self.z_km)):
            raise ValueError("position coordinates must be finite")
        if self.frame not in {"unspecified", "legacy_xy", "ecef", "eci"}:
            raise ValueError("position frame must be unspecified, legacy_xy, ecef, or eci")


@dataclass(slots=True)
class Node:
    """A typed network node with configurable physical and traffic properties."""

    node_id: str
    node_type: NodeType
    position: Position
    operational: bool = True
    packet_generation_rate_pps: float = 0.0
    default_packet_size_bytes: int = 1024
    traffic_priority: str = "medium"
    destination: str | None = None
    communication_range_km: float | None = None
    bandwidth_mbps: float = 100.0
    orbital_plane: str | None = None
    initial_orbital_phase_rad: float = 0.0
    orbital_period_s: float | None = None
    processing_capacity_pps: float | None = None
    processing_delay_ms: float = 0.0
    queue_length: int = 0
    utilization: float = 0.0
    attributes: dict[str, object] = field(default_factory=dict)
    orbit: OrbitalElements | None = None
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    altitude_m: float = 0.0

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ValueError("node_id must not be empty")
        if self.packet_generation_rate_pps < 0 or self.default_packet_size_bytes <= 0:
            raise ValueError("traffic rate must be nonnegative and packet size positive")
        if self.bandwidth_mbps <= 0:
            raise ValueError("bandwidth_mbps must be positive")
        if self.communication_range_km is not None and self.communication_range_km <= 0:
            raise ValueError("communication_range_km must be positive")
        if self.orbital_period_s is not None and self.orbital_period_s <= 0:
            raise ValueError("orbital_period_s must be positive")
        if self.processing_capacity_pps is not None and self.processing_capacity_pps <= 0:
            raise ValueError("processing_capacity_pps must be positive when provided")
        if self.processing_delay_ms < 0 or self.queue_length < 0:
            raise ValueError("processing delay and queue length must be nonnegative")
        if not 0.0 <= self.utilization <= 1.0:
            raise ValueError("utilization must be between 0 and 1")
        if self.traffic_priority not in {"low", "medium", "high"}:
            raise ValueError("traffic_priority must be low, medium, or high")
        if (self.latitude_deg is None) != (self.longitude_deg is None):
            raise ValueError("latitude_deg and longitude_deg must be provided together")
        if self.latitude_deg is not None:
            GeodeticPosition(self.latitude_deg, self.longitude_deg, self.altitude_m)
        elif not math.isfinite(self.altitude_m):
            raise ValueError("altitude_m must be finite")
        if self.orbit is not None and self.node_type is not NodeType.SATELLITE:
            raise ValueError("orbital elements are only valid for satellite nodes")


@dataclass(slots=True)
class Link:
    """Communication link parameters; distance and propagation are in km and ms."""

    source: str
    target: str
    distance_km: float
    propagation_latency_ms: float
    bandwidth_mbps: float
    packet_loss_probability: float = 0.0
    congestion: float = 0.0
    operational: bool = True
    transmission_overhead_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.distance_km < 0 or self.propagation_latency_ms < 0:
            raise ValueError("distance and latency must be nonnegative")
        if self.bandwidth_mbps <= 0:
            raise ValueError("bandwidth_mbps must be positive")
        if not 0 <= self.packet_loss_probability <= 1:
            raise ValueError("packet loss probability must be between 0 and 1")
        if not 0 <= self.congestion <= 1:
            raise ValueError("congestion must be between 0 and 1")


@dataclass(slots=True)
class Packet:
    """Packet lifecycle record; packet size is expressed in bytes."""

    packet_id: str
    source: str
    destination: str
    size_bytes: int
    generated_at_s: float
    state: PacketState = PacketState.GENERATED
    path: list[str] = field(default_factory=list)
    hop_count: int = 0
    reroute_count: int = 0
    delivered_at_s: float | None = None
    drop_reason: str | None = None
    current_location: str | None = None
    latency_s: float | None = None
    priority: str = "medium"

    def __post_init__(self) -> None:
        if not self.packet_id or not self.source or not self.destination:
            raise ValueError("packet ID, source, and destination are required")
        if self.size_bytes <= 0 or self.generated_at_s < 0:
            raise ValueError("packet size must be positive and generation time nonnegative")
        if self.current_location is None:
            self.current_location = self.source
        if self.priority not in {"low", "medium", "high"}:
            raise ValueError("priority must be low, medium, or high")
