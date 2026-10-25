"""Derive metrics from packet and resource observations."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from src.models.network import Packet, PacketState


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    generated: int
    delivered: int
    dropped: int
    timed_out: int
    pending: int
    packet_delivery_ratio: float
    throughput_bps: float
    mean_latency_s: float | None
    median_latency_s: float | None
    p95_latency_s: float | None
    reroutes: int
    hop_count_mean: float | None
    recovery_successes: int
    recovery_failures: int
    mean_recovery_time_s: float | None
    observation_window_s: float


def summarize(
    packets: list[Packet],
    observation_window_s: float,
    recovery_times_s: list[float],
    recovery_failures: int,
) -> MetricsSummary:
    """Compute metrics. PDR denominator includes all generated packets,
    including pending/censored packets at the horizon. Throughput is delivered
    payload bits divided by the fixed simulation observation window.
    """
    if observation_window_s <= 0:
        raise ValueError("observation_window_s must be positive")
    delivered = [p for p in packets if p.state is PacketState.DELIVERED]
    dropped = sum(p.state is PacketState.DROPPED for p in packets)
    timed_out = sum(p.state is PacketState.TIMED_OUT for p in packets)
    pending = sum(p.state is PacketState.PENDING for p in packets)
    latencies = sorted(p.latency_s for p in delivered if p.latency_s is not None)
    p95 = None
    if len(latencies) >= 20:
        # Nearest-rank percentile; require 20 samples to avoid presenting a
        # very small-sample maximum as a useful tail-latency estimate.
        p95 = latencies[max(0, int(0.95 * len(latencies) + 0.999999) - 1)]
    hop_counts = [p.hop_count for p in delivered]
    return MetricsSummary(
        generated=len(packets),
        delivered=len(delivered),
        dropped=dropped,
        timed_out=timed_out,
        pending=pending,
        packet_delivery_ratio=len(delivered) / len(packets) if packets else 0.0,
        throughput_bps=sum(p.size_bytes * 8 for p in delivered) / observation_window_s,
        mean_latency_s=mean(latencies) if latencies else None,
        median_latency_s=(latencies[(len(latencies) - 1) // 2] if len(latencies) % 2 else
                          (latencies[len(latencies)//2 - 1] + latencies[len(latencies)//2]) / 2)
        if latencies else None,
        p95_latency_s=p95,
        reroutes=sum(p.reroute_count for p in packets),
        hop_count_mean=mean(hop_counts) if hop_counts else None,
        recovery_successes=len(recovery_times_s),
        recovery_failures=recovery_failures,
        mean_recovery_time_s=mean(recovery_times_s) if recovery_times_s else None,
        observation_window_s=observation_window_s,
    )
