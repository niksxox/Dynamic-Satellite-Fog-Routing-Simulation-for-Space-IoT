"""Dijkstra-based routing over the dynamic topology graph.

The router works on the NetworkX graph maintained by `TopologyEngine`.
Physical eligibility (range and node-type compatibility) and operational
availability (node/link state) are distinct: only operational nodes and links
are traversable, and an explicitly failed link is never traversed even while
it remains physically eligible.

Two Dijkstra modes are provided:

* ``shortest_latency``: the edge weight is propagation latency plus any
  explicit transmission overhead, plus an optional size-dependent
  transmission delay when ``packet_size_bytes`` is given.
* ``multi_factor``: the edge weight is a normalized convex combination of
  latency, bandwidth penalty, packet-loss probability, and congestion, using
  the configured `RoutingWeights`. Routing cost (the optimized value) is kept
  separate from estimated physical path latency.

Results are structured `RoutingResult` objects. Unknown endpoints, failed
nodes, unavailable links, invalid edge attributes, and disconnected
destinations yield ``route_available=False`` with a reason instead of
inventing a route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import networkx as nx

from src.models.config import RoutingWeights, SimulationConfig

BITS_PER_BYTE = 8
BITS_PER_MEGABIT = 1_000_000.0


class RoutingMode(str, Enum):
    SHORTEST_LATENCY = "shortest_latency"
    MULTI_FACTOR = "multi_factor"


@dataclass(frozen=True, slots=True)
class RoutingResult:
    """Structured outcome of a routing query."""

    source: str
    destination: str
    algorithm: str
    path: list[str]
    total_cost: float
    estimated_latency_ms: float
    bottleneck_bandwidth_mbps: float
    delivery_reliability: float
    route_available: bool
    reason: str | None = None


class RoutingEngine:
    """Dijkstra-based router over a NetworkX topology graph."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()
        self.weights = self.config.weights

    def route(
        self,
        graph: nx.Graph,
        source: str,
        destination: str,
        mode: RoutingMode | str = RoutingMode.SHORTEST_LATENCY,
        weights: RoutingWeights | None = None,
        packet_size_bytes: int | None = None,
    ) -> RoutingResult:
        """Route from source to destination with the selected Dijkstra mode.

        Args:
            graph: NetworkX topology graph whose edges carry
                ``propagation_latency_ms``, ``bandwidth_mbps``,
                ``packet_loss_probability``, ``congestion``, ``operational``
                and optional ``transmission_overhead_ms`` attributes.
            source: source node id.
            destination: destination node id.
            mode: ``RoutingMode.SHORTEST_LATENCY`` or
                ``RoutingMode.MULTI_FACTOR``.
            weights: routing weights for multi-factor mode; defaults to the
                configured weights. Must be nonnegative and sum to one.
            packet_size_bytes: optional packet size in bytes. When given, each
                hop adds a size-dependent transmission delay of
                ``size_bytes * 8 / (bandwidth_mbps * 1e6)`` seconds converted
                to milliseconds. When None, only the fixed
                ``transmission_overhead_ms`` edge attribute is used; no packet
                size is assumed.

        Returns:
            A `RoutingResult`. ``route_available`` is False and ``reason``
            describes the outcome when no usable route exists.
        """
        mode = RoutingMode(mode) if isinstance(mode, str) else mode
        weights = weights or self.weights
        self._validate_weights(weights)
        if packet_size_bytes is not None and packet_size_bytes <= 0:
            raise ValueError("packet_size_bytes must be positive when provided")

        algorithm = mode.value
        if source not in graph:
            return self._unavailable(source, destination, algorithm, "unknown source node")
        if destination not in graph:
            return self._unavailable(source, destination, algorithm, "unknown destination node")
        if not bool(graph.nodes[source].get("operational", True)):
            return self._unavailable(source, destination, algorithm, "source node is not operational")
        if not bool(graph.nodes[destination].get("operational", True)):
            return self._unavailable(source, destination, algorithm, "destination node is not operational")
        if source == destination:
            return RoutingResult(
                source, destination, algorithm, [source], 0.0, 0.0, math.inf, 1.0, True, None
            )

        working = self._build_working_graph(
            graph, source, destination, weights, mode, packet_size_bytes
        )
        try:
            path = nx.dijkstra_path(working, source, destination, weight="cost")
        except nx.NetworkXNoPath:
            return self._unavailable(source, destination, algorithm, "no available path")

        total_cost = sum(
            float(working.edges[u, v]["cost"]) for u, v in zip(path, path[1:])
        )
        latency_ms, bottleneck, reliability = self._path_metrics(
            graph, path, packet_size_bytes
        )
        return RoutingResult(
            source,
            destination,
            algorithm,
            path,
            total_cost,
            latency_ms,
            bottleneck,
            reliability,
            True,
            None,
        )

    def _build_working_graph(
        self,
        graph: nx.Graph,
        source: str,
        destination: str,
        weights: RoutingWeights,
        mode: RoutingMode,
        packet_size_bytes: int | None,
    ) -> nx.Graph:
        """Copy operational nodes and valid links into a working graph.

        Non-operational nodes and links, and links with invalid or missing
        attributes, are excluded so Dijkstra never traverses them.
        """
        working = nx.Graph()
        metrics: dict[frozenset[str], dict[str, float]] = {}
        for node_id in graph.nodes:
            if bool(graph.nodes[node_id].get("operational", True)):
                working.add_node(node_id, **dict(graph.nodes[node_id]))
        for u, v, data in graph.edges(data=True):
            if u not in working or v not in working:
                continue
            if not bool(data.get("operational", True)):
                continue
            try:
                propagation = float(data.get("propagation_latency_ms", 0.0))
                overhead = float(data.get("transmission_overhead_ms", 0.0))
                bandwidth = float(data.get("bandwidth_mbps"))
                loss = float(data.get("packet_loss_probability", 0.0))
                congestion = float(data.get("congestion", 0.0))
            except (TypeError, ValueError):
                continue
            if (
                propagation < 0
                or bandwidth <= 0
                or not (0.0 <= loss <= 1.0)
                or not (0.0 <= congestion <= 1.0)
            ):
                continue
            if packet_size_bytes is not None:
                transmission = (
                    packet_size_bytes * BITS_PER_BYTE / (bandwidth * BITS_PER_MEGABIT) * 1000.0
                )
            else:
                transmission = 0.0
            latency = propagation + overhead + transmission
            key = frozenset((u, v))
            metrics[key] = {
                "latency": latency,
                "bandwidth": bandwidth,
                "loss": loss,
                "congestion": congestion,
            }
            working.add_edge(u, v, **dict(data), latency_ms=latency)

        if metrics:
            values = {
                name: [m[name] for m in metrics.values()]
                for name in ("latency", "bandwidth", "loss", "congestion")
            }
            ranges = {name: (min(vals), max(vals)) for name, vals in values.items()}
            for key, m in metrics.items():
                cost = (
                    weights.latency * self._normalize(m["latency"], *ranges["latency"])
                    + weights.bandwidth
                    * (1.0 - self._normalize(m["bandwidth"], *ranges["bandwidth"]))
                    + weights.loss * self._normalize(m["loss"], *ranges["loss"])
                    + weights.congestion * self._normalize(m["congestion"], *ranges["congestion"])
                )
                u, v = sorted(key)
                working.edges[u, v]["cost"] = float(cost)
        if mode is RoutingMode.SHORTEST_LATENCY:
            for u, v in working.edges:
                working.edges[u, v]["cost"] = float(working.edges[u, v]["latency_ms"])
        return working

    @staticmethod
    def _normalize(value: float, low: float, high: float) -> float:
        """Min-max normalize to [0, 1]; returns 0.0 when low == high."""
        if high == low:
            return 0.0
        return (value - low) / (high - low)

    @staticmethod
    def _path_metrics(
        graph: nx.Graph, path: list[str], packet_size_bytes: int | None
    ) -> tuple[float, float, float]:
        """Return estimated latency, bottleneck bandwidth, and reliability."""
        latency = 0.0
        bandwidths: list[float] = []
        reliability = 1.0
        for u, v in zip(path, path[1:]):
            data = graph.edges[u, v]
            bandwidth = float(data.get("bandwidth_mbps", math.inf))
            propagation = float(data.get("propagation_latency_ms", 0.0))
            overhead = float(data.get("transmission_overhead_ms", 0.0))
            loss = float(data.get("packet_loss_probability", 0.0))
            if packet_size_bytes is not None and bandwidth > 0:
                transmission = (
                    packet_size_bytes * BITS_PER_BYTE / (bandwidth * BITS_PER_MEGABIT) * 1000.0
                )
            else:
                transmission = 0.0
            latency += propagation + overhead + transmission
            bandwidths.append(bandwidth)
            reliability *= 1.0 - loss
        bottleneck = min(bandwidths) if bandwidths else math.inf
        return latency, bottleneck, reliability

    @staticmethod
    def _validate_weights(weights: RoutingWeights) -> None:
        values = (weights.latency, weights.bandwidth, weights.loss, weights.congestion)
        if any(value < 0 for value in values):
            raise ValueError("routing weights must be nonnegative")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("routing weights must sum to 1 within 1e-9")

    @staticmethod
    def _unavailable(
        source: str, destination: str, algorithm: str, reason: str
    ) -> RoutingResult:
        return RoutingResult(
            source,
            destination,
            algorithm,
            [],
            math.inf,
            math.inf,
            math.inf,
            0.0,
            False,
            reason,
        )
