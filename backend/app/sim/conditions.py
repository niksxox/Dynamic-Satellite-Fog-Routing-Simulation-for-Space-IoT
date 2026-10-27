"""Dynamic link and node failure/recovery conditions and risk model.

Maintains link and node states, generates stochastic and manual failure/recovery
events, computes real-time link operational properties, and calculates routing risk.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np

from app.sim.linkmath import (
    GSL_CAPACITY_MBPS,
    ISL_CAPACITY_MBPS,
    cong_loss,
    prop_ms,
)
from app.sim.topology import GroundStation, Topology

LinkId = Tuple[int, int]


def link_key(a: int, b: int) -> LinkId:
    """Return normalized link identifier tuple (min, max)."""
    return (a, b) if a < b else (b, a)


def link_id_str(a: int, b: int) -> str:
    """Return normalized link identifier string 'min-max'."""
    u, v = link_key(a, b)
    return f"{u}-{v}"


def node_name(i: int, n_sats: int, ground: Any) -> str:
    """Format node identifier: 'S014' for satellites, station name for ground nodes.

    Args:
        i: Node index.
        n_sats: Total number of satellites in the constellation.
        ground: List or collection of GroundStation objects.

    Returns:
        Formatted human-readable node name string.
    """
    if i < n_sats:
        return f"S{i:03d}"

    if ground:
        for gs in ground:
            if getattr(gs, "id", None) == i:
                return gs.name
            if isinstance(gs, dict) and gs.get("id") == i:
                return gs["name"]

    return f"G{i}"


@dataclass
class FailParams:
    """Parameters governing failure distributions and detection latency."""

    mtbf_link_s: float = 60000.0
    down_s: Tuple[float, float] = (20.0, 90.0)
    intensity: float = 1.0
    detect_delay_s: float = 1.0


class ConditionModel:
    """Dynamic network failure and degradation condition model."""

    def __init__(
        self,
        rng: np.random.Generator,
        params: FailParams,
        n_sats: int,
        ground: Any,
    ):
        self.rng = rng
        self.params = params
        self.n_sats = n_sats
        self.ground = ground

        # Persistent failure state keyed by LinkId
        self.down_until: Dict[LinkId, float] = {}
        self.last_fail_t: Dict[LinkId, float] = {}
        self.fail_seen_t: Dict[LinkId, float] = {}
        self.failed_nodes: Set[int] = set()
        self.node_fail_seen_t: Dict[int, float] = {}

    def step(self, topo: Topology, t: float, dt: float) -> List[Dict[str, Any]]:
        """Advance failure simulation by time step dt and return emitted events.

        1) Recoveries: For every link in down_until with finite value and t >= down_until,
           remove it and emit a link_restore event.
        2) Random failures: Iterate topo.isl + topo.gsl in sorted order. For each link
           currently up, test stochastic failure with probability p = 1 - exp(-dt*intensity/mtbf_link_s).
        """
        events: List[Dict[str, Any]] = []

        # 1) Recoveries
        recovered_links: List[LinkId] = []
        for key in sorted(self.down_until.keys()):
            end_t = self.down_until[key]
            if not math.isinf(end_t) and t >= end_t:
                recovered_links.append(key)

        for key in recovered_links:
            del self.down_until[key]
            name_a = node_name(key[0], self.n_sats, self.ground)
            name_b = node_name(key[1], self.n_sats, self.ground)
            events.append({
                "t": t,
                "level": "info",
                "kind": "link_restore",
                "msg": f"Link {name_a}-{name_b} restored",
            })

        # 2) Random failures
        # Collect unique topology links in deterministic sorted order
        all_links = sorted(list(set(link_key(u, v) for u, v in (topo.isl + topo.gsl))))
        up_links = [k for k in all_links if self.is_up(k[0], k[1], t)]

        n_up = len(up_links)
        if n_up > 0:
            draws = self.rng.random(n_up)
            p = 1.0 - math.exp(-dt * self.params.intensity / self.params.mtbf_link_s)

            # Up links with draw < p fail
            failing_indices = [idx for idx in range(n_up) if draws[idx] < p]
            for idx in failing_indices:
                link = up_links[idx]
                dur = float(self.rng.uniform(*self.params.down_s))
                self.down_until[link] = t + dur
                self.last_fail_t[link] = t
                self.fail_seen_t[link] = t

                name_a = node_name(link[0], self.n_sats, self.ground)
                name_b = node_name(link[1], self.n_sats, self.ground)
                events.append({
                    "t": t,
                    "level": "warn",
                    "kind": "link_fail",
                    "msg": f"Link {name_a}-{name_b} failed (random)",
                })

        return events

    def fail_link(
        self,
        a: int,
        b: int,
        t: float,
        duration: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Manually mark link (a, b) as failed.

        Args:
            a: First node index.
            b: Second node index.
            t: Time of failure event.
            duration: Outage duration in seconds (None = math.inf).

        Returns:
            Emitted failure event dict.
        """
        k = link_key(a, b)
        end_t = math.inf if duration is None else (t + duration)
        self.down_until[k] = end_t
        self.last_fail_t[k] = t
        self.fail_seen_t[k] = t

        name_a = node_name(k[0], self.n_sats, self.ground)
        name_b = node_name(k[1], self.n_sats, self.ground)
        return {
            "t": t,
            "level": "crit",
            "kind": "link_fail",
            "msg": f"Link {name_a}-{name_b} failed (manual)",
        }

    def restore_link(self, a: int, b: int, t: float) -> Optional[Dict[str, Any]]:
        """Manually restore link (a, b). Returns event dict or None if not down."""
        k = link_key(a, b)
        if k not in self.down_until:
            return None

        del self.down_until[k]
        name_a = node_name(k[0], self.n_sats, self.ground)
        name_b = node_name(k[1], self.n_sats, self.ground)
        return {
            "t": t,
            "level": "info",
            "kind": "link_restore",
            "msg": f"Link {name_a}-{name_b} restored",
        }

    def fail_node(self, i: int, t: float) -> Dict[str, Any]:
        """Manually mark node i as failed."""
        self.failed_nodes.add(i)
        self.node_fail_seen_t[i] = t
        name = node_name(i, self.n_sats, self.ground)
        return {
            "t": t,
            "level": "crit",
            "kind": "node_fail",
            "msg": f"Node {name} failed",
        }

    def restore_node(self, i: int, t: float) -> Optional[Dict[str, Any]]:
        """Manually restore node i."""
        if i not in self.failed_nodes:
            return None

        self.failed_nodes.discard(i)
        self.node_fail_seen_t.pop(i, None)
        name = node_name(i, self.n_sats, self.ground)
        return {
            "t": t,
            "level": "info",
            "kind": "node_restore",
            "msg": f"Node {name} restored",
        }

    def restore_all(self, t: float) -> None:
        """Clear all active link and node failures."""
        self.down_until.clear()
        self.failed_nodes.clear()
        self.fail_seen_t.clear()
        self.node_fail_seen_t.clear()

    def is_up(self, a: int, b: int, t: float) -> bool:
        """Return True if link (a, b) is operational at time t."""
        if a in self.failed_nodes or b in self.failed_nodes:
            return False
        k = link_key(a, b)
        if k in self.down_until:
            if t < self.down_until[k]:
                return False
        return True

    def failed_link_count(self, topo: Topology, t: float) -> int:
        """Return number of active topology links currently down."""
        unique_links = set(link_key(u, v) for u, v in (topo.isl + topo.gsl))
        return sum(1 for u, v in unique_links if not self.is_up(u, v, t))

    def failed_node_count(self) -> int:
        """Return number of currently failed nodes."""
        return len(self.failed_nodes)

    def link_props(self, topo: Topology, a: int, b: int) -> Dict[str, Any]:
        """Return link properties (dist_km, prop_ms, capacity_mbps, kind)."""
        k = link_key(a, b)
        is_isl = a < self.n_sats and b < self.n_sats
        kind = 0 if is_isl else 1
        capacity_mbps = ISL_CAPACITY_MBPS if kind == 0 else GSL_CAPACITY_MBPS

        if k in topo.dist:
            dist_km = topo.dist[k]
        else:
            p_a = (
                topo.pos[a]
                if a < self.n_sats
                else topo.ground_pos[a - self.n_sats]
            )
            p_b = (
                topo.pos[b]
                if b < self.n_sats
                else topo.ground_pos[b - self.n_sats]
            )
            dist_km = float(np.linalg.norm(p_a - p_b))

        prop = prop_ms(dist_km)
        return {
            "dist_km": dist_km,
            "prop_ms": prop,
            "capacity_mbps": capacity_mbps,
            "kind": kind,
        }

    def risk(
        self,
        a: int,
        b: int,
        t: float,
        rho: float = 0.0,
        weather: float = 0.0,
    ) -> float:
        """Calculate dynamic routing risk in [0, 1].

        Formula: max(loss_term, recent_fail_term, 0.0)
        where loss_term = clip((weather + cong_loss(rho)) * 10, 0, 1)
        and recent_fail_term = 0.6 * 0.5**((t - last_fail_t)/60) if last_fail_t else 0.
        """
        loss_term = float(np.clip((weather + cong_loss(rho)) * 10.0, 0.0, 1.0))
        k = link_key(a, b)
        if k in self.last_fail_t:
            dt_fail = max(0.0, t - self.last_fail_t[k])
            recent_fail_term = 0.6 * (0.5 ** (dt_fail / 60.0))
        else:
            recent_fail_term = 0.0

        return float(max(loss_term, recent_fail_term, 0.0))

    def visible_down(self, a: int, b: int, t: float) -> bool:
        """Check if link failure is visible to routing protocol after detect_delay_s."""
        if self.is_up(a, b, t):
            return False

        k = link_key(a, b)
        # Check link failure detection delay
        if k in self.fail_seen_t:
            if (t - self.fail_seen_t[k]) >= self.params.detect_delay_s:
                return True

        # Check endpoint node failure detection delay
        for node in (a, b):
            if node in self.failed_nodes and node in self.node_fail_seen_t:
                if (t - self.node_fail_seen_t[node]) >= self.params.detect_delay_s:
                    return True

        return False
