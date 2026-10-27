"""Adaptive multi-path router with risk, latency, congestion avoidance, and hysteresis."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import networkx as nx

from app.sim.conditions import ConditionModel, LinkId, link_key
from app.sim.linkmath import link_latency_ms
from app.sim.routing.cost import DEFAULT_WEIGHTS, link_cost
from app.sim.topology import Topology
from app.sim.traffic import Flow, Routes


@dataclass
class AdaptiveParams:
    """Parameters controlling adaptive traffic routing and hysteresis."""

    weights: Tuple[float, float, float] = DEFAULT_WEIGHTS
    chunks: int = 4
    stickiness: float = 0.9
    cadence_ticks: int = 5
    detect_delay_s: float = 1.0


class AdaptiveRouter:
    """Adaptive multi-path router.

    Performs incremental load assignment with chunking, avoids congested and risky links,
    respects detection delays for link failures, and utilizes stickiness to prevent
    unnecessary route flapping. Never transits intermediate ground stations.
    Does not modify ConditionModel state.
    """

    def __init__(
        self,
        cond: ConditionModel,
        params: Optional[Union[AdaptiveParams, Dict[str, Any]]] = None,
    ) -> None:
        self.cond = cond
        if params is None:
            self.params = AdaptiveParams()
        elif isinstance(params, dict):
            self.params = AdaptiveParams(**params)
        else:
            self.params = params

        self.prev_routes: Routes = {}
        self.reroutes: int = 0
        self.tick_count: int = 0
        self.last_edge_set: Optional[frozenset[LinkId]] = None
        self.last_down_visible: Optional[frozenset[LinkId]] = None
        self.last_route_ms: float = 0.0
        self.prev_primary_path: Dict[str, List[int]] = {}

    def update(
        self,
        topo: Topology,
        flows: Union[Sequence[Flow], Dict[str, Flow]],
        t: float,
        force: bool = False,
    ) -> Routes:
        """Compute adaptive multi-path routes for all active flows.

        Args:
            topo: Current Topology snapshot.
            flows: Traffic demand flows.
            t: Current simulation time in seconds.
            force: Force route recomputation regardless of cadence.

        Returns:
            Routes mapping flow id to chunks of (path, chunk_mbps).
        """
        if isinstance(flows, dict):
            flow_list = list(flows.values())
        else:
            flow_list = list(flows)

        current_edge_set = frozenset(
            link_key(u, v) for u, v in (topo.isl + topo.gsl)
        )
        current_down_visible = frozenset(
            k for k in current_edge_set if self.cond.visible_down(k[0], k[1], t)
        )

        cadence_hit = (self.tick_count % self.params.cadence_ticks == 0)
        edge_set_changed = (self.last_edge_set != current_edge_set)
        down_visible_changed = (self.last_down_visible != current_down_visible)

        should_recompute = (
            cadence_hit or force or edge_set_changed or down_visible_changed
        )
        self.tick_count += 1

        if not should_recompute:
            return self.prev_routes

        t_start = time.perf_counter()

        n_sats = len(topo.pos)
        n_ground = len(topo.ground_pos)
        ground_nodes = set(range(n_sats, n_sats + n_ground))
        if topo.gsl:
            for u, v in topo.gsl:
                if u >= n_sats:
                    ground_nodes.add(u)
                if v >= n_sats:
                    ground_nodes.add(v)

        # Graph contains all physical topology links that are NOT visible_down
        G = nx.Graph()
        for u, v in topo.isl + topo.gsl:
            k = link_key(u, v)
            if k in current_down_visible:
                continue
            if G.has_edge(u, v):
                continue

            props = self.cond.link_props(topo, u, v)
            capacity = float(props["capacity_mbps"])
            prop_delay = float(props["prop_ms"])

            lat_ms = float(link_latency_ms(prop_delay, 0.0))
            risk = float(self.cond.risk(u, v, t, rho=0.0))
            w = float(link_cost(lat_ms, 0.0, risk, self.params.weights))

            G.add_edge(
                u,
                v,
                w=w,
                load=0.0,
                capacity=capacity,
                prop_ms=prop_delay,
                risk=risk,
            )

        # Sort flows by descending offered demand
        flows_sorted = sorted(flow_list, key=lambda f: f.mbps, reverse=True)
        routes: Routes = {}

        for f in flows_sorted:
            if f.mbps <= 0.0:
                routes[f.id] = []
                primary_path = []
                prev_primary = self.prev_primary_path.get(f.id)
                if prev_primary is not None and primary_path != prev_primary:
                    self.reroutes += 1
                self.prev_primary_path[f.id] = primary_path
                continue

            chunks_count = max(1, self.params.chunks)
            q = f.mbps / chunks_count
            src, dst = f.src, f.dst

            # Identify sticky edges from previous paths of this flow
            prev_flow_routes = self.prev_routes.get(f.id, [])
            sticky_edges: set[Tuple[int, int]] = set()
            for prev_path, _ in prev_flow_routes:
                for i in range(len(prev_path) - 1):
                    sticky_edges.add(link_key(prev_path[i], prev_path[i + 1]))

            # Apply stickiness discount before routing this flow's chunks
            sticky_in_g: List[Tuple[int, int]] = []
            if self.params.stickiness > 0.0:
                for u, v in sticky_edges:
                    if G.has_edge(u, v):
                        G[u][v]["w"] *= self.params.stickiness
                        sticky_in_g.append((u, v))

            # Restrict transit through intermediate ground stations
            forbidden_ground = ground_nodes - {src, dst}
            sub_g = G.subgraph([n for n in G if n not in forbidden_ground])

            chunk_paths: List[List[int]] = []
            flow_unreachable = False

            for _ in range(chunks_count):
                try:
                    path = nx.dijkstra_path(sub_g, src, dst, weight="w")
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    flow_unreachable = True
                    break

                chunk_paths.append(path)

                # Update load and edge cost for edges along the chosen chunk path
                for i in range(len(path) - 1):
                    u, v = path[i], path[i + 1]
                    edge_data = G[u][v]
                    edge_data["load"] += q
                    cap = edge_data["capacity"]
                    rho = (
                        (edge_data["load"] / cap) if cap > 0.0 else 0.0
                    )
                    lat_ms = float(link_latency_ms(edge_data["prop_ms"], rho))
                    cost_unscaled = float(
                        link_cost(
                            lat_ms, rho, edge_data["risk"], self.params.weights
                        )
                    )
                    if (
                        link_key(u, v) in sticky_edges
                        and self.params.stickiness > 0.0
                    ):
                        edge_data["w"] = cost_unscaled * self.params.stickiness
                    else:
                        edge_data["w"] = cost_unscaled

            # Divide back stickiness discount after routing this flow's chunks
            if self.params.stickiness > 0.0:
                for u, v in sticky_in_g:
                    G[u][v]["w"] /= self.params.stickiness

            if flow_unreachable or not chunk_paths:
                routes[f.id] = []
                primary_path = []
            else:
                # Merge identical chunk paths
                merged: Dict[Tuple[int, ...], float] = {}
                for path in chunk_paths:
                    t_path = tuple(path)
                    merged[t_path] = merged.get(t_path, 0.0) + q

                result_chunks = [(list(p), mbps) for p, mbps in merged.items()]
                routes[f.id] = result_chunks

                # Primary path is the largest chunk's path
                primary_path = max(result_chunks, key=lambda c: c[1])[0]

            # Reroute tracking: compare largest chunk's path with previous primary path
            prev_primary = self.prev_primary_path.get(f.id)
            if prev_primary is not None:
                if primary_path != prev_primary:
                    self.reroutes += 1
            self.prev_primary_path[f.id] = primary_path

        self.last_edge_set = current_edge_set
        self.last_down_visible = current_down_visible
        self.prev_routes = routes
        self.last_route_ms = (time.perf_counter() - t_start) * 1000.0

        return routes
