"""Traffic specifications and SimPy packet-arrival process helpers."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Iterator

from src.models.network import Packet


@dataclass(frozen=True, slots=True)
class TrafficSpec:
    """Packet source definition.

    If ``schedule_s`` is supplied, packets are generated at those absolute
    simulation timestamps. Otherwise arrivals follow a Poisson process with
    exponential inter-arrival times and mean ``1 / rate_pps`` seconds.
    """

    source: str
    destination: str
    rate_pps: float = 1.0
    packet_size_bytes: int = 1024
    priority: str = "medium"
    schedule_s: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if not self.source or not self.destination:
            raise ValueError("traffic source and destination are required")
        if self.rate_pps < 0:
            raise ValueError("rate_pps must be nonnegative")
        if self.packet_size_bytes <= 0:
            raise ValueError("packet_size_bytes must be positive")
        if self.priority not in {"low", "medium", "high"}:
            raise ValueError("priority must be low, medium, or high")
        if self.schedule_s is not None:
            if any(t < 0 for t in self.schedule_s):
                raise ValueError("schedule timestamps must be nonnegative")
            if tuple(sorted(self.schedule_s)) != self.schedule_s:
                raise ValueError("schedule_s must be sorted")
        elif self.rate_pps <= 0:
            raise ValueError("rate_pps must be positive for stochastic traffic")


def arrival_times(spec: TrafficSpec, rng: random.Random, duration_s: float) -> Iterator[float]:
    """Yield arrivals strictly before the observation horizon."""
    if spec.schedule_s is not None:
        yield from (t for t in spec.schedule_s if t < duration_s)
        return
    t = 0.0
    while True:
        t += rng.expovariate(spec.rate_pps)
        if t >= duration_s:
            return
        yield t


def generator_process(
    env,
    spec: TrafficSpec,
    rng: random.Random,
    duration_s: float,
    create_packet: Callable[[TrafficSpec, float], Packet | None],
):
    """SimPy process that emits packets at generated arrival times."""
    for arrival in arrival_times(spec, rng, duration_s):
        delay = arrival - env.now
        if delay < 0:
            raise RuntimeError("traffic arrival process moved backwards in time")
        yield env.timeout(delay)
        if env.now >= duration_s:
            return
        if create_packet(spec, float(env.now)) is None:
            return
