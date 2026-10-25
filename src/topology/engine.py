"""NetworkX topology engine with explicit compatibility and range rules.

Satellite motion is a deterministic circular projection in the XY plane. Each
satellite is projected onto its orbital radius using its phase and period; this
is a visualization/topology approximation, not orbital mechanics.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import networkx as nx

from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Position

logger = logging.getLogger(__name__)
SPEED_OF_LIGHT_KM_S = 299_792.458
EARTH_RADIUS_KM = 6_371.0


def distance_km(a: Position, b: Position) -> float:
    """Return Euclidean separation in kilometers."""
    return math.sqrt((a.x_km - b.x_km) ** 2 + (a.y_km - b.y_km) ** 2 + (a.z_km - b.z_km) ** 2)


def propagation_delay_ms(distance: float) -> float:
    """Convert one-way propagation time to milliseconds for a km distance."""
    if distance < 0:
        raise ValueError("distance must be nonnegative")
    return distance / SPEED_OF_LIGHT_KM_S * 1000.0


def satellite_position(node: Node, time_s: float) -> Position:
    """Calculate a deterministic circular XY projection for a satellite node."""
    if node.node_type is not NodeType.SATELLITE:
        raise ValueError("satellite_position requires a satellite node")
    if node.orbital_period_s is None:
        raise ValueError(f"satellite {node.node_id} has no orbital_period_s")
    if time_s < 0:
        raise ValueError("time_s must be nonnegative")
    radius = math.hypot(node.position.x_km, node.position.y_km)
    if radius <= EARTH_RADIUS_KM:
        radius = EARTH_RADIUS_KM + 550.0
    omega = 2 * math.pi / node.orbital_period_s
    phase = node.initial_orbital_phase_rad + omega * time_s
    return Position(radius * math.cos(phase), radius * math.sin(phase), node.position.z_km)


@dataclass(frozen=True, slots=True)
class TopologyEvent:
    time_s: float
    event_type: str
    source: str
    target: str


class TopologyEngine:
    """Maintains currently available links in a simple undirected graph."""

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config
        self.nodes: dict[str, Node] = {}
        self.graph = nx.Graph()
        self.events: list[TopologyEvent] = []
        # Explicit link failures persist independently of physical eligibility.
        # A link in this set stays unavailable across topology reconciliation
        # until an explicit recovery event removes it.
        self._failed_links: set[frozenset[str]] = set()

    def initialize_network(self, nodes: list[Node], time_s: float = 0.0) -> nx.Graph:
        """Validate/store nodes and compute the initial available topology."""
        ids = [node.node_id for node in nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("node IDs must be unique")
        self.nodes = {node.node_id: node for node in nodes}
        self.graph = nx.Graph()
        for node in nodes:
            self.graph.add_node(node.node_id, model=node, node_type=node.node_type.value,
                                operational=node.operational, position=node.position)
        return self.update_topology(time_s)

    def update_satellite_positions(self, time_s: float) -> None:
        """Update position state for all satellites at a simulation timestamp."""
        for node in self.nodes.values():
            if node.node_type is NodeType.SATELLITE:
                node.position = satellite_position(node, time_s)
                if node.node_id in self.graph:
                    self.graph.nodes[node.node_id]["position"] = node.position

    def _range_for(self, a: Node, b: Node) -> float | None:
        pair = frozenset((a.node_type, b.node_type))
        c = self.config
        ranges = {
            frozenset((NodeType.SATELLITE,)): c.satellite_range_km,
            frozenset((NodeType.SATELLITE, NodeType.GROUND_STATION)): c.satellite_ground_range_km,
            frozenset((NodeType.GROUND_STATION, NodeType.FOG)): c.ground_fog_range_km,
            frozenset((NodeType.IOT, NodeType.GROUND_STATION)): c.iot_ground_range_km,
            frozenset((NodeType.IOT, NodeType.SATELLITE)): c.iot_satellite_range_km,
            frozenset((NodeType.FOG, NodeType.CLOUD)): c.fog_cloud_range_km,
        }
        return ranges.get(pair)

    @staticmethod
    def _compatible(a: Node, b: Node) -> bool:
        pair = frozenset((a.node_type, b.node_type))
        return pair in {
            frozenset((NodeType.SATELLITE,)),
            frozenset((NodeType.SATELLITE, NodeType.GROUND_STATION)),
            frozenset((NodeType.GROUND_STATION, NodeType.FOG)),
            frozenset((NodeType.IOT, NodeType.GROUND_STATION)),
            frozenset((NodeType.IOT, NodeType.SATELLITE)),
            frozenset((NodeType.FOG, NodeType.CLOUD)),
        }

    def set_node_operational(self, node_id: str, operational: bool, time_s: float) -> None:
        """Change node availability; next topology update applies link changes."""
        if node_id not in self.nodes:
            raise KeyError(node_id)
        self.nodes[node_id].operational = operational
        self.graph.nodes[node_id]["operational"] = operational
        self.update_topology(time_s)

    def set_link_operational(self, source: str, target: str, operational: bool, time_s: float) -> None:
        """Apply an explicit link outage/recovery without changing eligibility.

        The failure state is recorded in an explicit failure set that survives
        topology reconciliation, so a failed link stays unavailable across
        topology updates until a recovery event restores it.
        """
        if source not in self.nodes or target not in self.nodes:
            raise KeyError(f"unknown link endpoint: {source!r}, {target!r}")
        key = frozenset((source, target))
        if operational:
            self._failed_links.discard(key)
        else:
            self._failed_links.add(key)
        if not self.graph.has_edge(source, target):
            if operational:
                return
            a, b = self.nodes[source], self.nodes[target]
            d = distance_km(a.position, b.position)
            self.graph.add_edge(source, target, distance_km=d,
                                propagation_latency_ms=propagation_delay_ms(d),
                                bandwidth_mbps=min(a.bandwidth_mbps, b.bandwidth_mbps),
                                packet_loss_probability=0.0, congestion=0.0, operational=False)
            previous = True
        else:
            previous = bool(self.graph.edges[source, target].get("operational", True))
            self.graph.edges[source, target]["operational"] = operational
        if previous != operational:
            event_type = "link_up" if operational else "link_down"
            self.events.append(TopologyEvent(time_s, event_type, source, target))
            logger.info("link %s: %s <-> %s at %.3fs", event_type, source, target, time_s)

    def update_topology(self, time_s: float) -> nx.Graph:
        """Reconcile range-eligible links; unchanged states produce no events."""
        self.update_satellite_positions(time_s)
        prior = {frozenset((u, v)): data.copy() for u, v, data in self.graph.edges(data=True)}
        desired: dict[frozenset[str], dict[str, object]] = {}
        ids = list(self.nodes)
        for i, a_id in enumerate(ids):
            a = self.nodes[a_id]
            for b_id in ids[i + 1:]:
                b = self.nodes[b_id]
                if not a.operational or not b.operational or not self._compatible(a, b):
                    continue
                max_range = self._range_for(a, b)
                d = distance_km(a.position, b.position)
                if max_range is None or d > max_range:
                    continue
                key = frozenset((a_id, b_id))
                old = prior.get(key, {})
                desired[key] = {
                    "distance_km": d,
                    "propagation_latency_ms": propagation_delay_ms(d),
                    "bandwidth_mbps": min(a.bandwidth_mbps, b.bandwidth_mbps),
                    "packet_loss_probability": old.get("packet_loss_probability", 0.0),
                    "congestion": old.get("congestion", 0.0),
                    # Physical eligibility does not imply operational
                    # availability: an explicitly failed link stays down.
                    "operational": bool(old.get("operational", True)) and key not in self._failed_links,
                    "max_range_km": max_range,
                }
        self.graph.remove_edges_from(list(self.graph.edges))
        for key, attrs in desired.items():
            u, v = sorted(key)
            self.graph.add_edge(u, v, **attrs)
        old_keys, new_keys = set(prior), set(desired)
        for key in sorted(new_keys - old_keys, key=lambda k: sorted(k)):
            u, v = sorted(key)
            self.events.append(TopologyEvent(time_s, "link_up", u, v))
            logger.info("link up: %s <-> %s at %.3fs", u, v, time_s)
        for key in sorted(old_keys - new_keys, key=lambda k: sorted(k)):
            u, v = sorted(key)
            self.events.append(TopologyEvent(time_s, "link_down", u, v))
            logger.info("link down: %s <-> %s at %.3fs", u, v, time_s)
        return self.graph

    def topology_statistics(self) -> dict[str, int]:
        """Return current node/link counts and availability counts."""
        return {
            "nodes": self.graph.number_of_nodes(),
            "operational_nodes": sum(bool(d.get("operational")) for _, d in self.graph.nodes(data=True)),
            "links": self.graph.number_of_edges(),
            "operational_links": sum(bool(d.get("operational")) for _, _, d in self.graph.edges(data=True)),
        }

    @property
    def failed_links(self) -> set[frozenset[str]]:
        """Explicitly failed links, independent of physical range eligibility."""
        return set(self._failed_links)
