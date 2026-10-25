from __future__ import annotations

import streamlit as st

from dashboard.services.data import load_local_experiments
from dashboard.utils.formatting import format_metric
from dashboard.utils.errors import storage_error


def render(repository=None):
    st.markdown("## Mission overview")
    st.caption("A discrete-event research model for routing packets across a changing satellite, ground, and fog network.")
    results = st.session_state.get("dashboard_runs", {})
    experiments = st.session_state.get("dashboard_experiments", [])
    if not experiments:
        experiments = load_local_experiments()
    recent_runs = []
    for run_id, result in list(results.items())[-8:][::-1]:
        recent_runs.append({"run_id": run_id, "record_source": "browser session (volatile)", "status": "completed", "routing_algorithm": result.routing_mode,
            "seed": result.config.seed, "duration_s": result.end_time_s,
            "generated": result.metrics.generated, "delivered": result.metrics.delivered,
            "dropped": result.metrics.dropped, "timed_out": result.metrics.timed_out,
            "pending": result.metrics.pending})
    if repository:
        try:
            recent_runs = [dict(r, record_source="PostgreSQL") for r in repository.list_runs(8)] + recent_runs
            for item in repository.list_experiments(20):
                detail = repository.get_experiment_detail(item["experiment_id"])
                if detail and not any(e.get("experiment_id") == detail.get("experiment_id") for e in experiments):
                    detail["storage"] = "postgresql"
                    experiments.append(detail)
        except Exception as exc:
            st.warning(f"Could not load PostgreSQL history: {storage_error(exc)}")
    latest_result = next(iter(reversed(list(results.values()))), None)
    if latest_result:
        m = latest_result.metrics
        cols = st.columns(5)
        for col, label, value in zip(cols, ("Generated", "Delivered", "Dropped", "PDR", "Mean latency"),
            (m.generated, m.delivered, m.dropped, m.packet_delivery_ratio,
             None if m.mean_latency_s is None else m.mean_latency_s * 1000)):
            col.metric(label, format_metric(value, "ms" if label == "Mean latency" else ""))
        st.caption(f"Latest in-session run `{latest_result.run_id}` · {latest_result.routing_mode} · "
                   f"{m.pending} pending/censored · virtual duration {latest_result.end_time_s:g} s")
    else:
        st.info("No simulation has been run in this browser session yet. Open **Simulation Lab** to start one.")
    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("### Recent runs")
        if recent_runs:
            st.dataframe(recent_runs, use_container_width=True, hide_index=True)
        else:
            st.caption("No persisted or session-local runs are available.")
    with right:
        st.markdown("### Latest completed experiment")
        completed = [e for e in experiments if e.get("status") in {"completed", "completed_with_failures"}]
        if completed:
            exp = completed[0]
            success = sum(r.get("status") == "completed" for r in exp.get("rows", []))
            failed = len(exp.get("rows", [])) - success
            st.write(f"**{exp.get('scenario', 'scenario')}** · `{exp.get('experiment_id')}`")
            st.write(f"{success} successful run(s), {failed} failed · source: `{exp.get('storage', 'local export')}`")
        else:
            st.caption("No experiment export is available yet.")
    st.markdown("### Explore")
    st.write("Inspect the captured topology and packet routes, run a scenario, compare measured outputs, or review failure events and historical records using the sidebar.")
    st.info("Satellite motion uses a deterministic circular XY projection. Historical position snapshots are not currently recorded, so replay is based on the event timeline and route history rather than animated orbital state.")
