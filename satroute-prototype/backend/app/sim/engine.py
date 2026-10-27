"""Simulation engine coordinator for constellation dynamics, conditions, and routing."""

from __future__ import annotations

import copy
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from collections.abc import Callable

import numpy as np

from app.sim.conditions import ConditionModel, FailParams, link_key
from app.sim.constants import PROC_MS
from app.sim.metrics import MetricsTracker, NetworkTracker
from app.sim.orbit import (
    Constellation,
    ecef_to_latlon,
    latlon_to_ecef,
    positions_ecef,
    rephase_to,
    walker_delta,
)
from app.sim.routing import (
    AdaptiveParams,
    AdaptiveRouter,
    StaticRouter,
)
from app.sim.topology import (
    GroundStation,
    TopoParams,
    Topology,
    build_topology,
    default_ground_stations,
)
from app.sim.traffic import Flow, default_flows, evaluate


class Engine:
    """Core simulation engine driving orbital motion, network topology, routing, and metrics."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        seed: int = 42,
    ) -> None:
        self.seed = seed
        self.config = config or {}
        self.position_provider: Callable[[datetime], np.ndarray | None] | None = None
        self._init_state()

    def _init_state(self) -> None:
        """Initialize all constellation, ground, routing, and metric states."""
        cfg = self.config

        # 1. Constellation parameters
        num_sats = int(cfg.get("num_sats", 120))
        num_planes = int(cfg.get("num_planes", 12))
        f = int(cfg.get("f", 1))
        inc_deg = float(cfg.get("inc_deg", 53.0))
        alt_km = float(cfg.get("altitude_km", 550.0))

        self.constellation: Constellation = walker_delta(
            num_sats=num_sats,
            num_planes=num_planes,
            f=f,
            inc_deg=inc_deg,
            altitude_km=alt_km,
        )

        # 2. Ground stations and flows
        self.ground: List[GroundStation] = default_ground_stations(num_sats)
        self.flows: List[Flow] = default_flows(self.ground)
        # Preserve base flow demands for scaling
        self._base_mbps: Dict[str, float] = {f.id: f.mbps for f in self.flows}
        self.flow_scale: float = float(cfg.get("flow_scale", 1.0))

        # 3. Simulation time and control
        self.t: float = 0.0
        self.running: bool = True
        self.time_scale: float = float(cfg.get("time_scale", 20.0))
        self.tick_count: int = 0
        self.last_tick_ms: float = 0.0
        self._force_adaptive: bool = True
        self._force_topo_rebuild: bool = False

        # 4. Topology parameters
        self.topo_params = TopoParams()

        # 5. Conditions and failure parameters
        self.rng = np.random.default_rng(self.seed)
        fail_params = FailParams(
            mtbf_link_s=float(cfg.get("mtbf_link_s", 60000.0)),
            down_s=cfg.get("down_s", (20.0, 90.0)),
            intensity=float(cfg.get("intensity", 1.0)),
            detect_delay_s=float(cfg.get("detect_delay_s", 1.0)),
        )
        self.cond = ConditionModel(
            rng=self.rng,
            params=fail_params,
            n_sats=num_sats,
            ground=self.ground,
        )

        # 6. Routers
        weights = cfg.get("routing_weights", (1.0, 1.0, 1.0))
        chunks = int(cfg.get("routing_chunks", 4))
        stickiness = float(cfg.get("stickiness", 0.9))
        cadence_ticks = int(cfg.get("cadence_ticks", 5))
        detect_delay = float(cfg.get("detect_delay_s", 1.0))

        adaptive_params = AdaptiveParams(
            weights=weights,
            chunks=chunks,
            stickiness=stickiness,
            cadence_ticks=cadence_ticks,
            detect_delay_s=detect_delay,
        )
        self.static_router = StaticRouter()
        self.adaptive_router = AdaptiveRouter(self.cond, params=adaptive_params)

        # 7. Metrics and network tracking
        self.metrics_static = MetricsTracker()
        self.metrics_adaptive = MetricsTracker()
        self.network_tracker = NetworkTracker()

        # 8. Event buffers
        self.event_buffer: List[Dict[str, Any]] = []
        self.all_events: List[Dict[str, Any]] = []

        # 9. Initial topology and evaluation at t = 0
        pos0 = positions_ecef(self.constellation, 0.0        )
        self.last_pos = pos0
        self.last_position_source = "simulation"
        self.prev_topo: Topology = build_topology(
            pos0, self.ground, prev=None, params=self.topo_params
        )
        static_routes = self.static_router.update(self.prev_topo, self.flows)
        adaptive_routes = self.adaptive_router.update(
            self.prev_topo, self.flows, 0.0, force=True
        )

        self.eval_static = evaluate(
            self.prev_topo, self.cond, self.flows, static_routes, 0.0
        )
        self.eval_adaptive = evaluate(
            self.prev_topo, self.cond, self.flows, adaptive_routes, 0.0
        )

        self.metrics_static.update(
            0.0,
            0.0,
            self.eval_static,
            self.flows,
            self.static_router.reroutes,
            topo=self.prev_topo,
        )
        self.metrics_adaptive.update(
            0.0,
            0.0,
            self.eval_adaptive,
            self.flows,
            self.adaptive_router.reroutes,
            topo=self.prev_topo,
        )
        self.network_tracker.update(0.0, 0.0, self.prev_topo, self.cond)

    def tick(self, sim_dt: float) -> None:
        """Advance the simulation core by sim_dt seconds.

        Performs position propagation, topology construction, failure progression,
        static and adaptive routing updates, performance evaluation, and metrics tracking.
        """
        t_start = time.perf_counter()
        self.t += sim_dt

        # Update satellite orbital positions
        pos = self._positions_at(datetime.now(timezone.utc))
        if pos is None:
            pos = positions_ecef(self.constellation, self.t)
            self.last_position_source = "simulation"
        else:
            if pos.shape != (len(self.constellation), 3):
                raise ValueError(
                    f"Position provider returned shape {pos.shape}; "
                    f"expected {(len(self.constellation), 3)}"
                )
            self.last_position_source = "tle"
        self.last_pos = pos

        # Rebuild network topology snapshot
        prev = None if self._force_topo_rebuild else self.prev_topo
        topo = build_topology(
            pos, self.ground, prev=prev, params=self.topo_params
        )
        self.prev_topo = topo
        self._force_topo_rebuild = False

        # Step dynamic condition failures and recoveries
        step_events = self.cond.step(topo, self.t, sim_dt)
        if step_events:
            self.event_buffer.extend(step_events)
            self.all_events.extend(step_events)

        # Update routes for static and adaptive routers
        static_routes = self.static_router.update(topo, self.flows)
        adaptive_routes = self.adaptive_router.update(
            topo, self.flows, self.t, force=self._force_adaptive
        )
        self._force_adaptive = False

        # Evaluate performance for both routing solutions against current conditions
        self.eval_static = evaluate(
            topo, self.cond, self.flows, static_routes, self.t
        )
        self.eval_adaptive = evaluate(
            topo, self.cond, self.flows, adaptive_routes, self.t
        )

        # Update tracking metrics
        self.metrics_static.update(
            self.t,
            sim_dt,
            self.eval_static,
            self.flows,
            self.static_router.reroutes,
            topo=topo,
        )
        self.metrics_adaptive.update(
            self.t,
            sim_dt,
            self.eval_adaptive,
            self.flows,
            self.adaptive_router.reroutes,
            topo=topo,
        )
        self.network_tracker.update(self.t, sim_dt, topo, self.cond)

        self.tick_count += 1
        self.last_tick_ms = (time.perf_counter() - t_start) * 1000.0

    def step(self, dt_wall: float) -> Dict[str, Any]:
        """Advance simulation by dt_wall wall-clock seconds and return live frame dictionary."""
        if self.running:
            sim_dt = dt_wall * self.time_scale
            t0 = time.perf_counter()
            self.tick(sim_dt)
            self.last_tick_ms = (time.perf_counter() - t0) * 1000.0

        return self._build_frame(clear_events=True)

    def snapshot(self) -> Dict[str, Any]:
        """Return frame dictionary snapshot without advancing simulation time."""
        return self._build_frame(clear_events=False)

    def set_position_provider(
        self, provider: Callable[[datetime], np.ndarray | None] | None
    ) -> None:
        """Use an external Earth-fixed position source for topology and frame geometry."""
        self.position_provider = provider
        self._force_topo_rebuild = provider is not None
        self._force_adaptive = True

    def _positions_at(self, when: datetime) -> np.ndarray | None:
        if self.position_provider is None:
            return None
        return self.position_provider(when)

    def _build_frame(self, clear_events: bool = True) -> Dict[str, Any]:
        """Build frame dictionary matching SPEC section 12 exact structure."""
        # 1. Satellite positions and velocities
        pos_t = getattr(self, "last_pos", None)
        if pos_t is None:
            pos_t = positions_ecef(self.constellation, self.t)
        lat_t, lon_t, alt_t = ecef_to_latlon(pos_t)

        # Finite difference at t + 1.0 sim-second
        if self.last_position_source == "tle":
            pos_t1 = self._positions_at(datetime.now(timezone.utc) + timedelta(seconds=1))
            if pos_t1 is None:
                pos_t1 = pos_t
        else:
            pos_t1 = positions_ecef(self.constellation, self.t + 1.0)
        lat_t1, lon_t1, _ = ecef_to_latlon(pos_t1)

        dlat = lat_t1 - lat_t
        dlon = (lon_t1 - lon_t + 180.0) % 360.0 - 180.0

        velocity_scale = 1.0 if self.last_position_source == "tle" else self.time_scale
        vlat = dlat * velocity_scale
        vlon = dlon * velocity_scale

        sats_list: List[Dict[str, Any]] = []
        for i in range(len(self.constellation)):
            st = 1 if i in self.cond.failed_nodes else 0
            sats_list.append({
                "id": i,
                "lat": round(float(lat_t[i]), 4),
                "lon": round(float(lon_t[i]), 4),
                "alt": round(float(alt_t[i]), 4),
                "vlat": round(float(vlat[i]), 4),
                "vlon": round(float(vlon[i]), 4),
                "st": st,
            })

        # 2. Links
        links_list: List[Dict[str, Any]] = []
        topo = self.prev_topo
        all_links = sorted(
            list(set(link_key(u, v) for u, v in (topo.isl + topo.gsl)))
        )
        for u, v in all_links:
            k = link_key(u, v)
            link_info = self.eval_adaptive.links.get(k)
            if link_info:
                links_list.append({
                    "a": u,
                    "b": v,
                    "k": link_info["kind"],
                    "up": 1 if link_info["up"] else 0,
                    "rho": round(float(link_info["rho"]), 4),
                    "ms": round(float(link_info["ms"]), 4),
                    "loss": round(float(link_info["loss"]), 4),
                })

        # 3. Flows
        flows_list: List[Dict[str, Any]] = []
        for f in self.flows:
            fe_a = self.eval_adaptive.flows.get(f.id)
            fe_s = self.eval_static.flows.get(f.id)
            flows_list.append({
                "id": f.id,
                "adaptive": {
                    "paths": [
                        {"nodes": p, "mbps": round(float(m), 2)}
                        for p, m in (fe_a.paths if fe_a else [])
                    ],
                    "ms": round(float(fe_a.ms), 2) if fe_a else 0.0,
                    "pdr": round(float(fe_a.pdr), 4) if fe_a else 0.0,
                    "blackholed": fe_a.blackholed if fe_a else True,
                },
                "static": {
                    "paths": [
                        {"nodes": p, "mbps": round(float(m), 2)}
                        for p, m in (fe_s.paths if fe_s else [])
                    ],
                    "ms": round(float(fe_s.ms), 2) if fe_s else 0.0,
                    "pdr": round(float(fe_s.pdr), 4) if fe_s else 0.0,
                    "blackholed": fe_s.blackholed if fe_s else True,
                },
            })

        # 4. Metrics
        net_snap = self.network_tracker.snapshot_frame()
        metrics_dict = {
            "adaptive": self.metrics_adaptive.snapshot_frame(),
            "static": self.metrics_static.snapshot_frame(),
            "linkUptime": net_snap["linkUptime"],
            "activeFailures": net_snap["activeFailures"],
        }

        # 5. Events
        events_list = list(self.event_buffer)
        if clear_events:
            self.event_buffer.clear()

        return {
            "type": "frame",
            "positionSource": self.last_position_source,
            "t": round(self.t, 2),
            "scale": self.time_scale,
            "running": self.running,
            "tickMs": round(self.last_tick_ms, 2),
            "sats": sats_list,
            "links": links_list,
            "flows": flows_list,
            "metrics": metrics_dict,
            "events": events_list,
        }

    def init_message(self) -> Dict[str, Any]:
        """Generate static metadata initialization frame matching SPEC section 12."""
        return {
            "type": "init",
            "config": {
                "num_sats": len(self.constellation),
                "time_scale": self.time_scale,
                "cadence_ticks": self.adaptive_router.params.cadence_ticks,
            },
            "ground": [
                {
                    "id": gs.id,
                    "name": gs.name,
                    "lat": round(float(gs.lat), 4),
                    "lon": round(float(gs.lon), 4),
                }
                for gs in self.ground
            ],
            "flows": [
                {
                    "id": f.id,
                    "src": f.src,
                    "dst": f.dst,
                    "mbps": round(float(f.mbps), 2),
                }
                for f in self.flows
            ],
            "nSats": len(self.constellation),
            "planes": [int(p) for p in self.constellation.plane],
        }

    def apply_command(
        self,
        cmd: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Apply control command and return emitted events if applicable."""
        args = args or {}
        cmd_lower = cmd.lower()

        if cmd_lower == "play":
            self.running = True
            return None

        elif cmd_lower == "pause":
            self.running = False
            return None

        elif cmd_lower == "reset":
            self._init_state()
            return None

        elif cmd_lower == "set_scale":
            scale = args.get("scale", 20.0)
            self.time_scale = float(np.clip(float(scale), 1.0, 120.0))
            return None

        elif cmd_lower == "set_weights":
            a = float(args.get("a", 1.0))
            b = float(args.get("b", 1.0))
            c = float(args.get("c", 1.0))
            self.adaptive_router.params.weights = (a, b, c)
            self._force_adaptive = True
            return None

        elif cmd_lower == "fail_link":
            a = int(args["a"])
            b = int(args["b"])
            evt = self.cond.fail_link(a, b, self.t)
            self.event_buffer.append(evt)
            self.all_events.append(evt)
            self._force_adaptive = True
            return [evt]

        elif cmd_lower == "restore_link":
            a = int(args["a"])
            b = int(args["b"])
            evt = self.cond.restore_link(a, b, self.t)
            if evt:
                self.event_buffer.append(evt)
                self.all_events.append(evt)
            self._force_adaptive = True
            return [evt] if evt else []

        elif cmd_lower == "fail_sat":
            sat_id = int(args["id"])
            evt = self.cond.fail_node(sat_id, self.t)
            self.event_buffer.append(evt)
            self.all_events.append(evt)
            self._force_adaptive = True
            return [evt]

        elif cmd_lower == "restore_sat":
            sat_id = int(args["id"])
            evt = self.cond.restore_node(sat_id, self.t)
            if evt:
                self.event_buffer.append(evt)
                self.all_events.append(evt)
            self._force_adaptive = True
            return [evt] if evt else []

        elif cmd_lower == "move_sat":
            sat_id = int(args["id"])
            lat = float(args["lat"])
            lon = float(args["lon"])
            rephase_to(self.constellation, sat_id, lat, lon, self.t)
            self._force_topo_rebuild = True
            self._force_adaptive = True
            return None

        elif cmd_lower == "move_gs":
            gs_id = int(args["id"])
            lat = float(args["lat"])
            lon = float(args["lon"])
            for gs in self.ground:
                if gs.id == gs_id:
                    gs.lat = lat
                    gs.lon = lon
                    gs.ecef = latlon_to_ecef(lat, lon, 0.0)
                    break
            self._force_topo_rebuild = True
            self._force_adaptive = True
            return None

        elif cmd_lower == "set_flow_scale":
            factor = float(args.get("factor", 1.0))
            self.flow_scale = factor
            for f in self.flows:
                if f.id in self._base_mbps:
                    f.mbps = self._base_mbps[f.id] * self.flow_scale
            self._force_adaptive = True
            return None

        elif cmd_lower == "set_params":
            if "intensity" in args:
                self.cond.params.intensity = float(args["intensity"])
            return None

        elif cmd_lower == "add_flow":
            src = int(args["src"])
            dst = int(args["dst"])
            mbps = float(args["mbps"])
            f_id = args.get("id", f"{src}-{dst}")
            self._base_mbps[f_id] = mbps
            new_flow = Flow(id=f_id, src=src, dst=dst, mbps=mbps * self.flow_scale)
            self.flows.append(new_flow)
            self._force_adaptive = True
            return None

        elif cmd_lower == "remove_flow":
            f_id = str(args["id"])
            self.flows = [f for f in self.flows if f.id != f_id]
            self._base_mbps.pop(f_id, None)
            self._force_adaptive = True
            return None

        else:
            raise ValueError(f"Unknown command: {cmd}")


def run_headless(
    duration_s: float,
    seed: int = 42,
    sim_dt: float = 2.0,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run a headless constellation simulation for duration_s without wall-clock sleeps."""
    engine = Engine(config=config, seed=seed)
    n_ticks = int(duration_s / sim_dt)
    tick_times: List[float] = []

    for _ in range(n_ticks):
        t0 = time.perf_counter()
        engine.tick(sim_dt)
        tick_times.append((time.perf_counter() - t0) * 1000.0)

    adaptive_snap = engine.metrics_adaptive.snapshot()
    static_snap = engine.metrics_static.snapshot()
    network_snap = engine.network_tracker.snapshot()

    tick_p95 = float(np.percentile(tick_times, 95)) if tick_times else 0.0

    return {
        "adaptive": {
            **adaptive_snap,
            "outages_count": (
                len(engine.metrics_adaptive.completed_outage_durations)
                + sum(
                    1
                    for _, is_gap in engine.metrics_adaptive.outage_start.values()
                    if not is_gap
                )
            ),
            "completed_outages": len(
                engine.metrics_adaptive.completed_outage_durations
            ),
            "unrecovered_outages": sum(
                1
                for _, is_gap in engine.metrics_adaptive.outage_start.values()
                if not is_gap
            ),
            "throughput_mean": (
                engine.metrics_adaptive.cum_delivered_mb / duration_s
                if duration_s > 0
                else 0.0
            ),
        },
        "static": {
            **static_snap,
            "outages_count": (
                len(engine.metrics_static.completed_outage_durations)
                + sum(
                    1
                    for _, is_gap in engine.metrics_static.outage_start.values()
                    if not is_gap
                )
            ),
            "completed_outages": len(
                engine.metrics_static.completed_outage_durations
            ),
            "unrecovered_outages": sum(
                1
                for _, is_gap in engine.metrics_static.outage_start.values()
                if not is_gap
            ),
            "throughput_mean": (
                engine.metrics_static.cum_delivered_mb / duration_s
                if duration_s > 0
                else 0.0
            ),
        },
        "network": network_snap,
        "tick_ms_p95": tick_p95,
        "failure_events_count": len([
            e for e in engine.all_events if e.get("kind") == "link_fail"
        ]),
        "total_failures_count": engine.cond.failed_link_count(
            engine.prev_topo, engine.t
        ),
        "engine": engine,
    }
