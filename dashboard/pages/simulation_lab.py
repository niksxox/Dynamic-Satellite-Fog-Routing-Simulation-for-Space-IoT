from __future__ import annotations

import streamlit as st

from dashboard.services.simulation import run_paired_experiment, run_simulation
from dashboard.utils.formatting import format_metric
from src.experiments.reporting import export_experiment
from src.experiments.scenarios import SCENARIOS


def render(repository=None, storage="local"):
    st.markdown("## Simulation lab")
    st.caption("Runs use the same scenario builder as the experiment CLI. Each launch gets a new run ID; historical runs are not overwritten.")
    c1, c2 = st.columns(2)
    scenario = c1.selectbox("Scenario", list(SCENARIOS), format_func=lambda x: x.replace("_", " ").title())
    algorithm = c2.selectbox("Routing algorithm", ["shortest_latency", "multi_factor", "both"])
    c3, c4, c5 = st.columns(3)
    seed = c3.number_input("Random seed", min_value=0, max_value=2_147_483_647, value=7, step=1)
    duration = c4.number_input("Duration (virtual seconds)", min_value=0.1, max_value=300.0, value=2.0, step=0.5)
    satellites = c5.number_input("Satellite count", min_value=2, max_value=64, value=3, step=1)
    traffic = st.number_input("Base traffic intensity (packets/s)", min_value=0.1, max_value=1000.0, value=10.0, step=1.0,
        help="The high-traffic scenario multiplies this base rate by eight.")
    paired = st.checkbox("Run paired experiment when both algorithms are selected", value=True, disabled=algorithm != "both")
    st.caption(f"Storage: **{getattr(repository, 'backend', 'local session + local experiment exports') if storage == 'postgres' else 'local session + local experiment exports'}**")
    busy = st.session_state.get("dashboard_busy", False)
    button_label = ("Run paired experiment" if algorithm == "both" and paired else
                    "Run both separately" if algorithm == "both" else "Run simulation")
    if st.button(button_label, type="primary", disabled=busy):
        st.session_state["dashboard_busy"] = True
        try:
            if algorithm == "both" and paired:
                outdir = "experiment_output/dashboard"
                with st.spinner("Running both matched simulation arms…"):
                    bundle = run_paired_experiment(scenario, "both", int(seed), float(duration),
                        int(satellites), float(traffic), outdir, repository)
                    export_experiment(bundle, outdir)
                st.session_state.setdefault("dashboard_experiments", []).insert(0, bundle)
                st.success(f"Experiment {bundle['experiment_id']} finished: {bundle['status']} · storage {bundle['storage']}.")
                for row in bundle["rows"]:
                    if row["status"] != "completed":
                        st.error(f"{row['algorithm']} failed: {row.get('error')}")
                    elif row.get("expected_event_applied") is False:
                        st.warning(f"{row['algorithm']} completed, but the scheduled scenario event was not recorded.")
                st.info("Paired runs are saved in Experiment History. Per-run packet traces are available directly when running a single simulation.")
            elif algorithm == "both":
                st.info("Running both algorithms with a matched seed and configuration; separate run records will be created.")
                for mode in ("shortest_latency", "multi_factor"):
                    with st.spinner(f"Simulating {scenario.replace('_', ' ')} with {mode}…"):
                        result, metadata = run_simulation(scenario, mode, int(seed), float(duration),
                            int(satellites), float(traffic), repository)
                    st.session_state.setdefault("dashboard_runs", {})[result.run_id] = result
                    st.session_state.setdefault("dashboard_run_metadata", {})[result.run_id] = metadata
                    st.success(f"{mode}: {result.run_id} completed")
            else:
                mode = algorithm
                with st.spinner(f"Simulating {scenario.replace('_', ' ')} with {mode}…"):
                    result, metadata = run_simulation(scenario, mode, int(seed), float(duration),
                        int(satellites), float(traffic), repository)
                st.session_state.setdefault("dashboard_runs", {})[result.run_id] = result
                st.session_state.setdefault("dashboard_run_metadata", {})[result.run_id] = metadata
                if metadata["expected_event_applied"] is False:
                    st.warning("The run completed, but the expected scheduled event was not found in its event record.")
                st.success(f"Run {result.run_id} completed · {getattr(repository, 'backend', 'session memory')}")
                m = result.metrics
                cols = st.columns(5)
                for col, label, value, unit in zip(cols,
                    ("Delivered", "PDR", "Mean latency", "Throughput", "Reroutes"),
                    (m.delivered, m.packet_delivery_ratio,
                     None if m.mean_latency_s is None else m.mean_latency_s * 1000,
                     m.throughput_bps / 1_000_000, m.reroutes),
                    ("", "", "ms", "Mbps", "")):
                    col.metric(label, format_metric(value, unit))
                with st.expander("Run metadata and model notes", expanded=False):
                    st.json({**metadata, "wall_clock_runtime_s": result.wall_clock_runtime_s,
                             "events_truncated": result.events_truncated})
        except Exception as exc:
            if storage == "postgres":
                st.error(f"Simulation or persistence failed ({type(exc).__name__}).")
                st.caption("Check that PostgreSQL is running, DATABASE_URL is valid, and the dashboard can reach the configured host and database.")
            else:
                st.error(f"Simulation could not be completed: {type(exc).__name__}: {exc}")
        finally:
            st.session_state["dashboard_busy"] = False
    latest = next(iter(reversed(list(st.session_state.get("dashboard_runs", {}).values()))), None)
    if latest:
        st.caption(f"Most recent session trace: `{latest.run_id}` · open Network Explorer or Failure Replay to inspect its actual path and events.")
