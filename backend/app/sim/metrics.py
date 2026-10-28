"""Performance and network metrics tracking for constellation routing simulation."""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import networkx as nx
import numpy as np

from app.sim.conditions import ConditionModel
from app.sim.topology import Topology
from app.sim.traffic import EvalResult, Flow


class MetricsTracker:
    """Tracks latency, throughput, PDR, outages, and reroute metrics per algorithm."""

    def __init__(self, alpha: float = 0.2) -> None:
        self.alpha: float = alpha
        self.lat_ms: float = 0.0
        self._lat_initialized: bool = False
        self.pdr: float = 0.0
        self.thr_mbps: float = 0.0
        self.reroutes: int = 0
        self.reroutes_prev: int = 0
        self.reroute_times: deque[float] = deque()
        self.reroute_rate: int = 0

        # Outage episode tracking per flow: flow_id -> (start_time, is_coverage_gap)
        self.outage_start: Dict[str, Tuple[float, bool]] = {}
        self.completed_outage_durations: List[float] = []
        self.total_outage_s: float = 0.0

        # Coverage gaps tracking (separate from routable failure outages)
        self.coverage_gap_episodes: int = 0
        self.coverage_gap_s: float = 0.0

        # Cumulative benchmark metrics
        self.cum_delivered_mb: float = 0.0
        self.cum_offered_mb: float = 0.0
        self.cum_delivered_lat_prod: float = 0.0

        # Rolling history deques (maxlen=120)
        self.history_lat_ms: deque[float] = deque(maxlen=120)
        self.history_pdr: deque[float] = deque(maxlen=120)
        self.history_thr_mbps: deque[float] = deque(maxlen=120)
        self.history_reroutes: deque[int] = deque(maxlen=120)

    @property
    def recover_s(self) -> float:
        """Mean duration of completed routable outage episodes in seconds (excludes coverage gaps)."""
        if self.completed_outage_durations:
            return float(np.mean(self.completed_outage_durations))
        return 0.0

    @property
    def cum_pdr(self) -> float:
        """Cumulative packet delivery ratio across the simulation."""
        if self.cum_offered_mb > 0.0:
            return self.cum_delivered_mb / self.cum_offered_mb
        return 0.0

    @property
    def cum_lat_ms(self) -> float:
        """Delivered-traffic weighted mean latency across the simulation."""
        if self.cum_delivered_mb > 0.0:
            return self.cum_delivered_lat_prod / self.cum_delivered_mb
        return 0.0

    def update(
        self,
        t: float,
        dt: float,
        ev: EvalResult,
        flows: Union[Sequence[Flow], Dict[str, Flow]],
        reroutes_total: int,
        topo: Optional[Topology] = None,
    ) -> None:
        """Update metrics state at time t with time step dt."""
        # EWMA(alpha=0.2) of ev.lat_ms (only update when ev.thr_mbps > 0)
        if ev.thr_mbps > 0.0:
            if not self._lat_initialized:
                self.lat_ms = float(ev.lat_ms)
                self._lat_initialized = True
            else:
                self.lat_ms = (
                    self.alpha * float(ev.lat_ms)
                    + (1.0 - self.alpha) * self.lat_ms
                )

        self.pdr = float(ev.pdr)
        self.thr_mbps = float(ev.thr_mbps)

        # Detect increases in reroutes_total and prune older than 60 sim-seconds
        if reroutes_total > self.reroutes_prev:
            diff = reroutes_total - self.reroutes_prev
            for _ in range(diff):
                self.reroute_times.append(t)
            self.reroutes_prev = reroutes_total
        self.reroutes = reroutes_total

        while self.reroute_times and self.reroute_times[0] < (t - 60.0):
            self.reroute_times.popleft()
        self.reroute_rate = len(self.reroute_times)

        # Outage episode tracking per flow
        flow_list = (
            list(flows.values()) if isinstance(flows, dict) else list(flows)
        )

        # Prepare physical graph if any flow dropped to 0 to check if physical path exists
        g_phys: Optional[nx.Graph] = None
        all_stations: Optional[set[int]] = None

        for f in flow_list:
            fe = ev.flows.get(f.id)
            deliv = fe.delivered_mbps if fe else 0.0
            if deliv <= 0.0:
                if f.id not in self.outage_start:
                    # Episode starts: check whether flow has a physical path (ignoring failures)
                    if g_phys is None:
                        g_phys = nx.Graph()
                        if topo is not None:
                            g_phys.add_edges_from(topo.isl + topo.gsl)
                            n_sats = len(topo.pos)
                            all_stations = set(
                                range(n_sats, n_sats + len(topo.ground_pos))
                            )
                        else:
                            g_phys.add_edges_from(ev.links.keys())
                            all_stations = {fl.src for fl in flow_list} | {
                                fl.dst for fl in flow_list
                            }

                    # Flow has physical path if connected without intermediate ground transit
                    forbidden = all_stations - {f.src, f.dst}
                    sub = g_phys.subgraph(
                        [n for n in g_phys if n not in forbidden]
                    )
                    has_phys_path = (
                        f.src in sub
                        and f.dst in sub
                        and nx.has_path(sub, f.src, f.dst)
                    )

                    is_coverage_gap = not has_phys_path
                    self.outage_start[f.id] = (t, is_coverage_gap)
            else:
                if f.id in self.outage_start:
                    start_t, is_coverage_gap = self.outage_start.pop(f.id)
                    dur = t - start_t
                    if is_coverage_gap:
                        self.coverage_gap_episodes += 1
                        self.coverage_gap_s += dur
                    else:
                        self.completed_outage_durations.append(dur)
                        self.total_outage_s += dur

        # Cumulative metrics for benchmarks
        offered_mbps = sum(f.mbps for f in flow_list)
        self.cum_delivered_mb += ev.thr_mbps * dt
        self.cum_offered_mb += offered_mbps * dt
        self.cum_delivered_lat_prod += ev.lat_ms * ev.thr_mbps * dt

        # Rolling history
        self.history_lat_ms.append(self.lat_ms)
        self.history_pdr.append(self.pdr)
        self.history_thr_mbps.append(self.thr_mbps)
        self.history_reroutes.append(self.reroutes)

    def snapshot(self) -> Dict[str, Any]:
        """Summary metrics snapshot."""
        return {
            "latMs": round(self.lat_ms, 2),
            "pdr": round(self.pdr * 100.0, 2),
            "thrMbps": round(self.thr_mbps, 2),
            "reroutes": self.reroutes,
            "rerouteRate": self.reroute_rate,
            "recoverS": round(self.recover_s, 2),
            "cum_pdr": round(self.cum_pdr * 100.0, 2),
            "cum_lat_ms": round(self.cum_lat_ms, 2),
            "coverage_gap_episodes": self.coverage_gap_episodes,
            "coverage_gap_s": round(self.coverage_gap_s, 2),
        }

    def snapshot_frame(self) -> Dict[str, Any]:
        """Snapshot live metrics using ratios for PDR to match the frame contract."""
        return {
            "latMs": round(self.lat_ms, 2),
            "pdr": round(self.pdr, 4),
            "thrMbps": round(self.thr_mbps, 2),
            "reroutes": self.reroutes,
            "rerouteRate": self.reroute_rate,
            "recoverS": round(self.recover_s, 2),
        }


class NetworkTracker:
    """Tracks physical network availability and active component failures."""

    def __init__(self) -> None:
        self.failed_link_seconds: float = 0.0
        self.existing_link_seconds: float = 0.0
        self.link_uptime: float = 1.0
        self.active_failures: int = 0

    def update(
        self,
        t: float,
        dt: float,
        topo: Topology,
        cond: ConditionModel,
    ) -> None:
        """Update network uptime and failure counts."""
        num_links = len(set(topo.isl) | set(topo.gsl))
        n_failed_links = cond.failed_link_count(topo, t)
        n_failed_nodes = cond.failed_node_count()

        self.failed_link_seconds += n_failed_links * dt
        self.existing_link_seconds += num_links * dt

        if self.existing_link_seconds > 0.0:
            self.link_uptime = 1.0 - (
                self.failed_link_seconds / self.existing_link_seconds
            )
        else:
            self.link_uptime = 1.0

        self.active_failures = n_failed_links + n_failed_nodes

    def snapshot(self) -> Dict[str, Any]:
        """Return network uptime as a percentage and active failure count."""
        return {
            "linkUptime": round(self.link_uptime * 100.0, 2),
            "activeFailures": self.active_failures,
        }

    def snapshot_frame(self) -> Dict[str, Any]:
        """Return live-frame metrics with a ratio for frontend percentage formatting."""
        return {
            "linkUptime": round(self.link_uptime, 4),
            "activeFailures": self.active_failures,
        }
