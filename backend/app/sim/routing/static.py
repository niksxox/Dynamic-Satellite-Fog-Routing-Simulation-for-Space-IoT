"""Static shortest-path router based on physical link distances."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple, Union

import networkx as nx
import numpy as np

from app.sim.conditions import LinkId, link_key
from app.sim.topology import Topology
from app.sim.traffic import Flow, Routes


class StaticRouter:
    """Static shortest-path router.

    Maintains held shortest physical distance paths. Ignores link failures and
    congestion. Recomputes only when links become physically absent from the topology.
    Never passes through ground stations as intermediate transit nodes.
    """

    def __init__(self) -> None:
        self.paths: Dict[str, List[int]] = {}
        self.reroutes: int = 0
        self._cached_edge_set: Optional[frozenset[LinkId]] = None
        self._graph: Optional[nx.Graph] = None

    def update(
        self,
        topo: Topology,
        flows: Union[Sequence[Flow], Dict[str, Flow]],
    ) -> Routes:
        """Update static routes for flows over constellation topology.

        Args:
            topo: Current Topology snapshot.
            flows: Traffic flows as sequence or dict.

        Returns:
            Routes mapping flow id to single chunk of (path, flow.mbps).
        """
        if isinstance(flows, dict):
            flow_list = list(flows.values())
        else:
            flow_list = list(flows)

        n_sats = len(topo.pos)
        n_ground = len(topo.ground_pos)
        ground_nodes = set(range(n_sats, n_sats + n_ground))
        if topo.gsl:
            for u, v in topo.gsl:
                if u >= n_sats:
                    ground_nodes.add(u)
                if v >= n_sats:
                    ground_nodes.add(v)

        physical_edges = frozenset(
            link_key(u, v) for u, v in (topo.isl + topo.gsl)
        )

        # Rebuild physical graph only if edge set changed
        if self._graph is None or self._cached_edge_set != physical_edges:
            G = nx.Graph()
            for u, v in topo.isl + topo.gsl:
                k = link_key(u, v)
                if G.has_edge(u, v):
                    continue
                if k in topo.dist:
                    d = float(topo.dist[k])
                else:
                    p_u = (
                        topo.pos[u]
                        if u < n_sats
                        else topo.ground_pos[u - n_sats]
                    )
                    p_v = (
                        topo.pos[v]
                        if v < n_sats
                        else topo.ground_pos[v - n_sats]
                    )
                    d = float(np.linalg.norm(p_u - p_v))
                G.add_edge(u, v, w=d)
            self._graph = G
            self._cached_edge_set = physical_edges

        routes: Routes = {}

        for f in flow_list:
            held_path = self.paths.get(f.id)
            path_valid = False

            if (
                held_path
                and len(held_path) >= 2
                and held_path[0] == f.src
                and held_path[-1] == f.dst
            ):
                # Verify every hop physically still exists in topo
                if all(
                    link_key(held_path[i], held_path[i + 1]) in physical_edges
                    for i in range(len(held_path) - 1)
                ):
                    path_valid = True

            if path_valid and held_path is not None:
                chosen_path = held_path
            else:
                # Recompute shortest path avoiding other ground stations as transit
                forbidden = ground_nodes - {f.src, f.dst}
                sub_g = self._graph.subgraph(
                    [n for n in self._graph if n not in forbidden]
                )
                try:
                    new_path = nx.dijkstra_path(sub_g, f.src, f.dst, weight="w")
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    new_path = []

                if held_path and held_path != new_path:
                    self.reroutes += 1

                self.paths[f.id] = new_path
                chosen_path = new_path

            if chosen_path:
                routes[f.id] = [(chosen_path, f.mbps)]
            else:
                routes[f.id] = []

        return routes
