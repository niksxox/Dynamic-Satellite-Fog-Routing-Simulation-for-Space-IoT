"""Unit tests for the constellation simulation engine (backend/app/sim/engine.py)."""

import json
from typing import Any, Dict
import numpy as np
import pytest

from app.sim.engine import Engine, run_headless
from app.sim.orbit import ecef_to_latlon, positions_ecef

try:
    import orjson

    def dumps_json(obj: Any) -> bytes:
        return orjson.dumps(obj)

except ImportError:

    def dumps_json(obj: Any) -> bytes:
        return json.dumps(obj).encode("utf-8")


def test_1_determinism():
    """1. Determinism: run_headless(300, seed=42) twice -> identical summary dicts."""
    res1 = run_headless(300.0, seed=42, sim_dt=2.0)
    res2 = run_headless(300.0, seed=42, sim_dt=2.0)

    # Exclude wall-clock timing and engine object from direct dict equality
    t1 = res1.pop("tick_ms_p95", None)
    t2 = res2.pop("tick_ms_p95", None)
    res1.pop("engine", None)
    res2.pop("engine", None)

    assert t1 is not None and t1 > 0.0
    assert t2 is not None and t2 > 0.0
    assert res1 == res2, "Non-deterministic run_headless output for identical seed"


def test_2_step_output_spec_keys():
    """2. step() output has exactly the SPEC section 12 frame keys;

    sats has 120 entries; flows has 8; every link entry has keys a,b,k,up,rho,ms,loss.
    """
    engine = Engine(seed=42)
    frame = engine.step(dt_wall=0.1)

    # SPEC Section 12 required frame keys
    expected_frame_keys = {
        "type",
        "positionSource",
        "t",
        "scale",
        "running",
        "tickMs",
        "sats",
        "links",
        "flows",
        "metrics",
        "events",
    }
    assert set(frame.keys()) == expected_frame_keys, f"Frame keys mismatch: {set(frame.keys())}"
    assert frame["type"] == "frame"

    # Sats array
    assert len(frame["sats"]) == 120
    expected_sat_keys = {"id", "lat", "lon", "alt", "vlat", "vlon", "st"}
    for sat in frame["sats"]:
        assert set(sat.keys()) == expected_sat_keys

    # Flows array
    assert len(frame["flows"]) == 8
    expected_flow_keys = {"id", "adaptive", "static"}
    expected_subflow_keys = {"paths", "ms", "pdr", "blackholed"}
    for flow in frame["flows"]:
        assert set(flow.keys()) == expected_flow_keys
        assert set(flow["adaptive"].keys()) == expected_subflow_keys
        assert set(flow["static"].keys()) == expected_subflow_keys

    # Links array
    assert len(frame["links"]) > 0
    expected_link_keys = {"a", "b", "k", "up", "rho", "ms", "loss"}
    for link in frame["links"]:
        assert set(link.keys()) == expected_link_keys

    # Metrics dictionary
    expected_metrics_keys = {"adaptive", "static", "linkUptime", "activeFailures"}
    assert set(frame["metrics"].keys()) == expected_metrics_keys
    expected_algo_metric_keys = {
        "latMs",
        "pdr",
        "thrMbps",
        "reroutes",
        "rerouteRate",
        "recoverS",
    }
    assert set(frame["metrics"]["adaptive"].keys()) == expected_algo_metric_keys
    assert set(frame["metrics"]["static"].keys()) == expected_algo_metric_keys


def test_frame_metrics_use_ratio_values():
    """Live PDR and link uptime are ratios consumed as percentages by the UI."""
    engine = Engine(seed=42)
    frame = engine.step(dt_wall=0.1)

    assert 0.0 <= frame["metrics"]["adaptive"]["pdr"] <= 1.0
    assert 0.0 <= frame["metrics"]["static"]["pdr"] <= 1.0
    assert 0.0 <= frame["metrics"]["linkUptime"] <= 1.0
    reported_uptime = engine.network_tracker.snapshot()["linkUptime"]
    assert 1.0 < reported_uptime <= 100.0


def test_3_command_effects_link_failure():
    """3. Command effects: after fail_link on a hop in the static primary path of some flow,

    within a few ticks that flow's static entry has blackholed True and pdr 0.
    """
    engine = Engine(seed=42)
    engine.step(0.1)

    target_flow = "LON-NYC"
    fe_s = engine.eval_static.flows.get(target_flow)
    assert fe_s is not None and len(fe_s.paths) > 0
    primary_path = fe_s.paths[0][0]

    # Select a hop on the static path to fail
    u, v = primary_path[0], primary_path[1]
    engine.apply_command("fail_link", {"a": u, "b": v})

    # Step forward
    frame = None
    for _ in range(3):
        frame = engine.step(0.1)

    target_entry = next(f for f in frame["flows"] if f["id"] == target_flow)
    assert target_entry["static"]["blackholed"] is True
    assert target_entry["static"]["pdr"] == 0.0


def test_4_move_sat():
    """4. move_sat on sat 37 to (10,20): a frame afterwards shows sat 37 at lat/lon within 0.5 deg of (10,20) at that moment; and orbit keeps moving afterwards."""
    engine = Engine(seed=42)
    engine.step(0.1)

    target_sat = 37
    target_lat = 10.0
    target_lon = 20.0

    engine.apply_command("move_sat", {"id": target_sat, "lat": target_lat, "lon": target_lon})
    frame_after = engine.step(0.1)

    sat_entry = next(s for s in frame_after["sats"] if s["id"] == target_sat)
    assert abs(sat_entry["lat"] - target_lat) <= 0.5, f"Lat {sat_entry['lat']} not within 0.5 deg of {target_lat}"
    assert abs(sat_entry["lon"] - target_lon) <= 0.5, f"Lon {sat_entry['lon']} not within 0.5 deg of {target_lon}"

    # Verify orbit continues moving
    lat1, lon1 = sat_entry["lat"], sat_entry["lon"]
    frame_later = None
    for _ in range(10):
        frame_later = engine.step(0.1)

    sat_entry_later = next(s for s in frame_later["sats"] if s["id"] == target_sat)
    lat2, lon2 = sat_entry_later["lat"], sat_entry_later["lon"]
    assert (abs(lat2 - lat1) > 0.01) or (abs(lon2 - lon1) > 0.01), "Satellite orbit did not advance after rephasing"


def test_5_pause_play_scale_reset():
    """5. pause: t does not advance; play resumes. set_scale clamps. reset returns t to 0."""
    engine = Engine(seed=42)
    engine.step(0.1)
    t1 = engine.t
    assert t1 > 0.0

    # Pause
    engine.apply_command("pause")
    engine.step(0.1)
    engine.step(0.1)
    assert engine.t == t1, f"Time advanced while paused: {engine.t} != {t1}"

    # Play
    engine.apply_command("play")
    engine.step(0.1)
    assert engine.t > t1, f"Time did not advance after play: {engine.t} <= {t1}"

    # set_scale clamps to [1, 120]
    engine.apply_command("set_scale", {"scale": 500})
    assert engine.time_scale == 120.0
    engine.apply_command("set_scale", {"scale": -5})
    assert engine.time_scale == 1.0

    # Reset
    engine.apply_command("reset")
    assert engine.t == 0.0
    assert engine.tick_count == 0


def test_6_unknown_command():
    """6. Unknown command raises ValueError; the engine keeps working afterwards."""
    engine = Engine(seed=42)
    with pytest.raises(ValueError):
        engine.apply_command("invalid_cmd_xyz")

    # Engine continues working
    frame = engine.step(0.1)
    assert frame["type"] == "frame"
    assert frame["t"] > 0.0


def test_7_performance_and_frame_size():
    """7. Perf: p95 of tickMs over 200 live steps (dt_wall=0.1) < 80 ms (print it).

    Frame JSON size (orjson if installed else json) < 60 KB (print it).
    """
    engine = Engine(seed=42)
    tick_times = []
    last_frame = None

    for _ in range(200):
        frame = engine.step(dt_wall=0.1)
        tick_times.append(engine.last_tick_ms)
        last_frame = frame

    p95_tick_ms = float(np.percentile(tick_times, 95))
    print(f"\nLive step p95 tick time over 200 steps: {p95_tick_ms:.2f} ms")
    assert p95_tick_ms < 80.0, f"p95 tickMs {p95_tick_ms:.2f} ms not < 80 ms"

    # Frame size check
    frame_bytes = dumps_json(last_frame)
    frame_size_kb = len(frame_bytes) / 1024.0
    print(f"Frame JSON payload size: {frame_size_kb:.2f} KB")
    assert frame_size_kb < 60.0, f"Frame size {frame_size_kb:.2f} KB not < 60 KB"
