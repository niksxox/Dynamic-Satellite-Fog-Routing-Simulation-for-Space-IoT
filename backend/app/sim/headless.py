"""Headless benchmark execution and acceptance validation for SatRoute."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.sim.engine import Engine, run_headless


def format_table(
    title: str,
    summary: Dict[str, Any],
    sim_duration: float,
) -> str:
    """Format aligned comparison table between Static and Adaptive routing."""
    s = summary["static"]
    a = summary["adaptive"]
    net = summary["network"]

    s_gap_str = f"{s.get('coverage_gap_episodes', 0)} ({s.get('coverage_gap_s', 0.0):.1f}s)"
    a_gap_str = f"{a.get('coverage_gap_episodes', 0)} ({a.get('coverage_gap_s', 0.0):.1f}s)"

    lines = [
        f"=== {title} ===",
        f"{'Metric':<32} | {'Static':<16} | {'Adaptive':<16}",
        f"{'-'*32}-+-{'-'*16}-+-{'-'*16}",
        f"{'Mean Latency (ms, cumulative)':<32} | {s['cum_lat_ms']:<16.2f} | {a['cum_lat_ms']:<16.2f}",
        f"{'PDR % (cumulative)':<32} | {s['cum_pdr']:<16.2f} | {a['cum_pdr']:<16.2f}",
        f"{'Throughput (Mbps, mean)':<32} | {s['throughput_mean']:<16.2f} | {a['throughput_mean']:<16.2f}",
        f"{'Reroutes':<32} | {s['reroutes']:<16} | {a['reroutes']:<16}",
        f"{'Mean Recovery Time (s)':<32} | {s['recoverS']:<16.2f} | {a['recoverS']:<16.2f}",
        f"{'Outages (count)':<32} | {s['outages_count']:<16} | {a['outages_count']:<16}",
        f"{'Coverage Gaps (count, s)':<32} | {s_gap_str:<16} | {a_gap_str:<16}",
        f"{'Link Uptime %':<32} | {net['linkUptime']:<16.2f} | {net['linkUptime']:<16.2f}",
        f"{'Failure Events Count':<32} | {summary['failure_events_count']:<16} | {summary['failure_events_count']:<16}",
        f"{'Tick Time p95 (ms)':<32} | {summary['tick_ms_p95']:<16.2f} | {summary['tick_ms_p95']:<16.2f}",
    ]
    return "\n".join(lines)


def run_scenario_1() -> Dict[str, Any]:
    """Run baseline headless scenario 1 (1800 sim-seconds, defaults, seed 42)."""
    return run_headless(duration_s=1800.0, seed=42, sim_dt=2.0)


def run_scenario_2() -> Tuple[Dict[str, Any], float, float]:
    """Run scenario 2 with manual link failure on primary path of LON-NYC at t=300, restored at t=420."""
    engine = Engine(seed=42)
    duration_s = 1800.0
    sim_dt = 2.0
    n_ticks = int(duration_s / sim_dt)

    target_flow = "LON-NYC"
    failed_isl: Optional[Tuple[int, int]] = None
    t_failed = 300.0
    t_restored = 420.0

    adaptive_recovered_t: Optional[float] = None
    static_recovered_t: Optional[float] = None

    tick_times: List[float] = []

    for _ in range(n_ticks):
        # Check for injection at t == 300
        if math_close(engine.t, t_failed, tol=sim_dt / 2.0) and failed_isl is None:
            # Find an ISL on the Adaptive primary path of LON-NYC
            fe_a = engine.eval_adaptive.flows.get(target_flow)
            if fe_a and fe_a.paths:
                primary_path = fe_a.paths[0][0]
                for idx in range(len(primary_path) - 1):
                    u, v = primary_path[idx], primary_path[idx + 1]
                    if u < 120 and v < 120:  # ISL
                        failed_isl = (u, v)
                        break

            if failed_isl is None:
                # Fallback ISL if none found on path
                failed_isl = (0, 1)

            engine.apply_command("fail_link", {"a": failed_isl[0], "b": failed_isl[1]})

        # Check for restoration at t == 420
        if (
            failed_isl is not None
            and math_close(engine.t, t_restored, tol=sim_dt / 2.0)
        ):
            engine.apply_command("restore_link", {"a": failed_isl[0], "b": failed_isl[1]})

        t0 = time.perf_counter()
        engine.tick(sim_dt)
        tick_times.append((time.perf_counter() - t0) * 1000.0)

        # Monitor recovery after failure
        if failed_isl is not None and engine.t > t_failed:
            if adaptive_recovered_t is None:
                fe_a = engine.eval_adaptive.flows.get(target_flow)
                if fe_a and fe_a.delivered_mbps > 0.0:
                    adaptive_recovered_t = engine.t

            if engine.t >= t_restored and static_recovered_t is None:
                fe_s = engine.eval_static.flows.get(target_flow)
                if fe_s and fe_s.delivered_mbps > 0.0:
                    static_recovered_t = engine.t

    adaptive_recovery_time = (
        (adaptive_recovered_t - t_failed)
        if adaptive_recovered_t is not None
        else 0.0
    )
    static_blackhole_time = (
        (static_recovered_t - t_failed)
        if static_recovered_t is not None
        else (t_restored - t_failed)
    )

    adaptive_snap = engine.metrics_adaptive.snapshot()
    static_snap = engine.metrics_static.snapshot()
    network_snap = engine.network_tracker.snapshot()
    tick_p95 = float(np.percentile(tick_times, 95)) if tick_times else 0.0

    summary = {
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
            "throughput_mean": engine.metrics_adaptive.cum_delivered_mb / duration_s,
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
            "throughput_mean": engine.metrics_static.cum_delivered_mb / duration_s,
        },
        "network": network_snap,
        "tick_ms_p95": tick_p95,
        "failure_events_count": len([
            e for e in engine.all_events if e.get("kind") == "link_fail"
        ]),
    }
    return summary, adaptive_recovery_time, static_blackhole_time


def math_close(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


def main() -> None:
    # Scenario 1: Baseline defaults
    s1_summary = run_scenario_1()
    print()
    print(format_table("SCENARIO 1: DEFAULT CONFIGURATION (1800 s)", s1_summary, 1800.0))
    print(f"Total link failures that happened: {s1_summary['failure_events_count']}")
    print()

    # Scenario 2: Manual ISL failure on LON-NYC primary path
    s2_summary, a_recov, s_blackhole = run_scenario_2()
    print(format_table("SCENARIO 2: TARGETED ISL FAILURE t=300..420 s (LON-NYC)", s2_summary, 1800.0))
    print(f"Total link failures that happened: {s2_summary['failure_events_count']}")
    print(f"Time until Adaptive delivered again: {a_recov:.1f} s")
    print(f"Static blackholed for: {s_blackhole:.1f} s")
    print()


if __name__ == "__main__":
    main()
