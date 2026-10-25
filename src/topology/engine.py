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
from src.orbit.frames import (ecef_to_eci, ecef_to_geodetic, geodetic_to_ecef,
                              ground_elevation_deg)
from src.orbit.geometry import (distance_km, line_of_sight,
                                satellite_to_satellite_eligible,
                                satellite_to_ground_eligible)
from src.orbit.models import GeodeticPosition, OrbitalElements
from src.orbit.propagation import propagate_circular

logger = logging.getLogger(__name__)
SPEED_OF_LIGHT_KM_S = 299_792.458
EARTH_RADIUS_KM = 6_371.0  # Compatibility constant retained for old imports.


def propagation_delay_ms(distance: float) -> float:
    """Convert one-way propagation time to milliseconds for a km distance."""
    if distance < 0:
        raise ValueError("distance must be nonnegative")
    return distance / SPEED_OF_LIGHT_KM_S * 1000.0


def satellite_position(node: Node, time_s: float) -> Position:
    """Compatibility-only XY circular projection used by ``legacy_xy`` configs."""
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
    return Position(radius * math.cos(phase), radius * math.sin(phase), node.position.z_km,
                    frame="legacy_xy")


@dataclass(frozen=True, slots=True)
class TopologyEvent:
    time_s: float
    event_type: str
    source: str
    target: str
    details: dict[str, object] | None = None


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
        self._quality_overrides: dict[frozenset[str], dict[str, float]] = {}
        self._terrestrial_ecef: dict[str, Position] = {}
        self._orbital_elements: dict[str, OrbitalElements] = {}

    def initialize_network(self, nodes: list[Node], time_s: float = 0.0) -> nx.Graph:
        """Validate/store nodes and compute the initial available topology."""
        ids = [node.node_id for node in nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("node IDs must be unique")
        self.nodes = {node.node_id: node for node in nodes}
        self._failed_links.clear()
        self._quality_overrides.clear()
        self._terrestrial_ecef.clear()
        self._orbital_elements.clear()
        if self.config.orbital_model == "circular_two_body":
            self._prepare_physical_positions(nodes)
        self.graph = nx.Graph()
        for node in nodes:
            self.graph.add_node(node.node_id, model=node, node_type=node.node_type.value,
                                operational=node.operational, position=node.position)
        return self.update_topology(time_s)

    def update_satellite_positions(self, time_s: float) -> None:
        """Propagate satellites and rotate Earth-fixed nodes into the shared ECI frame."""
        for node in self.nodes.values():
            if self.config.orbital_model == "circular_two_body" and node.node_type is NodeType.SATELLITE:
                node.position = propagate_circular(self._orbital_elements[node.node_id], time_s,
                    self.config.earth_mu_km3_s2, self.config.earth_radius_km)
                self.graph.nodes[node.node_id]["position"] = node.position
            elif self.config.orbital_model == "circular_two_body":
                node.position = ecef_to_eci(self._terrestrial_ecef[node.node_id], time_s,
                                              self.config.reference_epoch_unix_s)
                self.graph.nodes[node.node_id]["position"] = node.position
            elif node.node_type is NodeType.SATELLITE:
                node.position = satellite_position(node, time_s)
                if node.node_id in self.graph:
                    self.graph.nodes[node.node_id]["position"] = node.position

    def _prepare_physical_positions(self, nodes: list[Node]) -> None:
        for node in nodes:
            if node.node_type is NodeType.SATELLITE:
                elements = node.orbit
                if elements is None:
                    radius = math.sqrt(node.position.x_km**2 + node.position.y_km**2 + node.position.z_km**2)
                    if radius <= self.config.earth_radius_km:
                        radius = self.config.earth_radius_km + 550.0
                        phase = node.initial_orbital_phase_rad
                    else:
                        phase = math.atan2(node.position.y_km, node.position.x_km)
                    elements = OrbitalElements(radius, argument_of_latitude_rad=phase)
                if elements.semi_major_axis_km <= self.config.earth_radius_km:
                    raise ValueError(f"satellite {node.node_id} orbit intersects configured Earth")
                self._orbital_elements[node.node_id] = elements
            else:
                if node.latitude_deg is not None:
                    ecef = geodetic_to_ecef(GeodeticPosition(node.latitude_deg,
                        node.longitude_deg, node.altitude_m), self.config.earth_radius_km,
                        self.config.earth_flattening)
                else:
                    if node.position.frame not in {"unspecified", "ecef"}:
                        raise ValueError(f"terrestrial node {node.node_id} must be specified in ECEF")
                    ecef = Position(node.position.x_km, node.position.y_km,
                                    node.position.z_km, frame="ecef")
                radius = math.sqrt(ecef.x_km**2 + ecef.y_km**2 + ecef.z_km**2)
                if radius < self.config.earth_radius_km - 100.0 or radius > self.config.earth_radius_km + 100.0:
                    raise ValueError(f"terrestrial node {node.node_id} is not within 100 km of the configured Earth surface; provide geodetic ground coordinates")
                self._terrestrial_ecef[node.node_id] = ecef

    def _orbit(self, node: Node) -> OrbitalElements:
        return self._orbital_elements[node.node_id]

    def _physical_geometry(self, a: Node, b: Node, max_range: float, time_s: float):
        """Return visibility and explainable geometry diagnostics for a supported pair."""
        if a.node_type is NodeType.SATELLITE and b.node_type is NodeType.SATELLITE:
            d = distance_km(a.position, b.position)
            visible = satellite_to_satellite_eligible(a.position, b.position, max_range,
                self.config.earth_radius_km, self.config.earth_flattening)
            los = line_of_sight(a.position, b.position, self.config.earth_radius_km,
                                flattening=self.config.earth_flattening)
            return visible, d, {"line_of_sight": los, "geometry": "satellite_satellite"}
        satellite, station = (a, b) if a.node_type is NodeType.SATELLITE else (b, a)
        if satellite.node_type is NodeType.SATELLITE and station.node_type in {NodeType.GROUND_STATION, NodeType.IOT}:
            d = distance_km(satellite.position, station.position)
            ecef = self._terrestrial_ecef[station.node_id]
            geo = (GeodeticPosition(station.latitude_deg, station.longitude_deg, station.altitude_m)
                   if station.latitude_deg is not None else ecef_to_geodetic(ecef,
                       self.config.earth_radius_km, self.config.earth_flattening))
            elevation = ground_elevation_deg(satellite.position, ecef, geo, time_s,
                                              self.config.reference_epoch_unix_s)
            visible, diagnostics = satellite_to_ground_eligible(satellite.position, ecef,
                geo, time_s, max_range, self.config.earth_radius_km,
                self.config.minimum_ground_elevation_deg, self.config.reference_epoch_unix_s,
                self.config.earth_flattening)
            los = diagnostics["line_of_sight"]
            return visible, d, {"line_of_sight": los, "elevation_deg": elevation,
                "minimum_elevation_deg": self.config.minimum_ground_elevation_deg,
                "geometry": "satellite_ground"}
        d = distance_km(a.position, b.position)
        return d <= max_range + 1e-6, d, {"geometry": "range_only"}

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
        was_operational = self.graph.has_edge(source, target) and bool(self.graph.edges[source, target].get("operational", False))
        if operational:
            self._failed_links.discard(key)
        else:
            self._failed_links.add(key)
        if not self.graph.has_edge(source, target):
            # Keep an outage override without creating a physically impossible
            # graph edge. It will take effect if the pair becomes eligible.
            return
        else:
            attrs = self.graph.edges[source, target]
            attrs["administratively_enabled"] = key not in self._failed_links
            now_operational = (attrs["administratively_enabled"] and
                bool(self.graph.nodes[source].get("operational", True)) and
                bool(self.graph.nodes[target].get("operational", True)))
            attrs["operational"] = now_operational
        if self.graph.has_edge(source, target) and was_operational != now_operational:
            event_type = "link_up" if now_operational else "link_down"
            self.events.append(TopologyEvent(time_s, event_type, source, target))
            logger.info("link %s: %s <-> %s at %.3fs", event_type, source, target, time_s)

    def set_link_conditions(
        self,
        source: str,
        target: str,
        time_s: float,
        *,
        congestion: float | None = None,
        packet_loss_probability: float | None = None,
    ) -> None:
        """Update quality attributes and retain them across topology updates."""
        key = frozenset((source, target))
        if not self.graph.has_edge(source, target):
            raise KeyError(f"link {source!r}<->{target!r} is not currently eligible")
        changes: dict[str, float] = {}
        if congestion is not None:
            if not 0.0 <= congestion <= 1.0:
                raise ValueError("congestion must be between 0 and 1")
            changes["congestion"] = congestion
        if packet_loss_probability is not None:
            if not 0.0 <= packet_loss_probability <= 1.0:
                raise ValueError("packet_loss_probability must be between 0 and 1")
            changes["packet_loss_probability"] = packet_loss_probability
        self.graph.edges[source, target].update(changes)
        self._quality_overrides.setdefault(key, {}).update(changes)
        if changes:
            self.events.append(TopologyEvent(time_s, "link_conditions_changed", source, target))

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
                if not self._compatible(a, b):
                    continue
                # Preserve historical XY semantics: failed nodes disappear
                # from the legacy topology. Physical mode keeps geometry and
                # reports node availability independently.
                if self.config.orbital_model != "circular_two_body" and (not a.operational or not b.operational):
                    continue
                max_range = self._range_for(a, b)
                if max_range is None:
                    continue
                if self.config.orbital_model == "circular_two_body":
                    visible, d, diagnostics = self._physical_geometry(a, b, max_range, time_s)
                    if not visible:
                        continue
                else:
                    d = distance_km(a.position, b.position)
                    visible, diagnostics = d <= max_range, {"geometry": "legacy_xy"}
                    if not visible:
                        continue
                key = frozenset((a_id, b_id))
                old = prior.get(key, {})
                admin_enabled = key not in self._failed_links
                desired[key] = {
                    "distance_km": d,
                    "propagation_latency_ms": propagation_delay_ms(d),
                    "bandwidth_mbps": min(a.bandwidth_mbps, b.bandwidth_mbps),
                    "packet_loss_probability": self._quality_overrides.get(key, {}).get(
                        "packet_loss_probability", old.get("packet_loss_probability", 0.0)
                    ),
                    "congestion": self._quality_overrides.get(key, {}).get(
                        "congestion", old.get("congestion", 0.0)
                    ),
                    # Physical eligibility does not imply operational
                    # availability: an explicitly failed link stays down.
                    "geometrically_visible": True,
                    "administratively_enabled": admin_enabled,
                    "nodes_operational": bool(a.operational and b.operational),
                    "operational": bool(a.operational and b.operational and admin_enabled),
                    "max_range_km": max_range,
                    **diagnostics,
                }
        self.graph.remove_edges_from(list(self.graph.edges))
        for key, attrs in desired.items():
            u, v = sorted(key)
            self.graph.add_edge(u, v, **attrs)
        old_keys, new_keys = set(prior), set(desired)
        if self.config.orbital_model == "circular_two_body":
            for key in sorted(new_keys - old_keys, key=lambda k: sorted(k)):
                u, v = sorted(key)
                self.events.append(TopologyEvent(time_s, "link_geometrically_available", u, v,
                    {k: desired[key][k] for k in ("distance_km", "line_of_sight", "elevation_deg", "minimum_elevation_deg", "geometrically_visible") if k in desired[key]}))
                if desired[key]["operational"]:
                    self.events.append(TopologyEvent(time_s, "link_up", u, v,
                        {"geometrically_visible": True, "administratively_enabled": desired[key]["administratively_enabled"]}))
            for key in sorted(old_keys - new_keys, key=lambda k: sorted(k)):
                u, v = sorted(key)
                self.events.append(TopologyEvent(time_s, "link_geometrically_unavailable", u, v,
                    {"reason": "range, elevation, or Earth-visibility constraint no longer satisfied"}))
                if prior[key].get("operational", True):
                    self.events.append(TopologyEvent(time_s, "link_down", u, v,
                        {"geometrically_visible": False, "administratively_enabled": prior[key].get("administratively_enabled", True)}))
            for key in sorted(old_keys & new_keys, key=lambda k: sorted(k)):
                old_up, new_up = bool(prior[key].get("operational", True)), bool(desired[key].get("operational", True))
                if old_up != new_up:
                    u, v = sorted(key)
                    self.events.append(TopologyEvent(time_s, "link_up" if new_up else "link_down", u, v,
                        {"geometrically_visible": True, "administratively_enabled": desired[key]["administratively_enabled"]}))
        for key in sorted(new_keys - old_keys, key=lambda k: sorted(k)):
            if bool(desired[key].get("operational", True)) and self.config.orbital_model != "circular_two_body":
                u, v = sorted(key)
                self.events.append(TopologyEvent(time_s, "link_up", u, v))
                logger.info("link up: %s <-> %s at %.3fs", u, v, time_s)
        for key in sorted(old_keys - new_keys, key=lambda k: sorted(k)):
            if bool(prior[key].get("operational", True)) and self.config.orbital_model != "circular_two_body":
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
