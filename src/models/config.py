"""Validated simulation configuration and routing weights."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RoutingWeights:
    latency: float = 0.45
    bandwidth: float = 0.20
    loss: float = 0.20
    congestion: float = 0.15

    def __post_init__(self) -> None:
        values = (self.latency, self.bandwidth, self.loss, self.congestion)
        if any(value < 0 for value in values):
            raise ValueError("routing weights must be nonnegative")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("routing weights must sum to 1 within 1e-9")


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Settings needed by the initial topology and model foundation."""

    seed: int = 7
    duration_s: float = 120.0
    topology_update_interval_s: float = 5.0
    satellite_range_km: float = 2500.0
    satellite_ground_range_km: float = 2200.0
    ground_fog_range_km: float = 150.0
    iot_ground_range_km: float = 30.0
    iot_satellite_range_km: float = 1500.0
    fog_cloud_range_km: float = 1000.0
    satellite_bandwidth_mbps: float = 100.0
    terrestrial_bandwidth_mbps: float = 1000.0
    max_packet_retries: int = 3
    packet_timeout_s: float = 30.0
    route_computation_delay_ms: float = 1.0
    # False gives each direction an independent link resource (full duplex).
    # True makes both directions contend for the same serialization resource.
    half_duplex_links: bool = False
    fog_default_servers: int = 1
    max_generated_packets: int = 100_000
    max_event_records: int = 250_000
    weights: RoutingWeights = field(default_factory=RoutingWeights)

    def __post_init__(self) -> None:
        positive = (self.duration_s, self.topology_update_interval_s, self.satellite_range_km,
                    self.satellite_ground_range_km, self.ground_fog_range_km,
                    self.iot_ground_range_km, self.iot_satellite_range_km,
                    self.fog_cloud_range_km, self.satellite_bandwidth_mbps,
                    self.terrestrial_bandwidth_mbps, self.packet_timeout_s)
        if any(value <= 0 for value in positive):
            raise ValueError("durations, ranges, and bandwidths must be positive")
        if self.max_packet_retries < 0:
            raise ValueError("max_packet_retries must be nonnegative")
        if self.route_computation_delay_ms < 0:
            raise ValueError("route_computation_delay_ms must be nonnegative")
        if self.fog_default_servers < 1:
            raise ValueError("fog_default_servers must be at least 1")
        if self.max_generated_packets < 1 or self.max_event_records < 1:
            raise ValueError("simulation record limits must be positive")
