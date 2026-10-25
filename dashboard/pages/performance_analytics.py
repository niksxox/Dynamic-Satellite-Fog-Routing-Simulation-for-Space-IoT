from __future__ import annotations

import streamlit as st

from dashboard.components.charts import experiment_chart
from dashboard.services.data import all_experiment_rows, filtered_comparison, load_local_experiments
from dashboard.utils.formatting import compatible_rows
from dashboard.utils.errors import storage_error


def render(repository=None):
    st.markdown("## Performance analytics")
    bundles = list(st.session_state.get("dashboard_experiments", []))
    for item in load_local_experiments():
        if not any(x.get("experiment_id") == item.get("experiment_id") for x in bundles):
            bundles.append(item)
    if repository:
        try:
            for experiment in repository.list_experiments(100):
                detail = repository.get_experiment_detail(experiment["experiment_id"])
                if detail and not any(x.get("experiment_id") == detail.get("experiment_id") for x in bundles):
                    bundles.append(detail)
        except Exception as exc:
            st.warning(f"Could not load PostgreSQL experiments: {storage_error(exc)}")
    rows = all_experiment_rows(bundles)
    if not rows:
        st.info("No experiment rows are available. Run a paired experiment in Simulation Lab or load local experiment exports.")
        return
    scenarios = sorted({r.get("scenario") for r in rows if r.get("scenario")})
    algorithms = sorted({r.get("algorithm") for r in rows if r.get("algorithm")})
    seeds = sorted({r.get("seed") for r in rows if r.get("seed") is not None})
    f1, f2, f3 = st.columns(3)
    selected_scenarios = f1.multiselect("Scenarios", scenarios, default=scenarios)
    selected_algorithms = f2.multiselect("Algorithms", algorithms, default=algorithms)
    selected_seeds = f3.multiselect("Seeds", seeds, default=seeds)
    paired_only = st.checkbox("Only include matched, completed seed/configuration pairs", value=True)
    subset = [r for r in rows if r.get("scenario") in selected_scenarios
        and r.get("algorithm") in selected_algorithms and r.get("seed") in selected_seeds]
    if paired_only:
        subset = compatible_rows(subset)
    if not subset:
        st.warning("No compatible paired records match these filters. Broaden the filters or turn off paired-only filtering to inspect individual runs.")
        return
    summary, paired, _ = filtered_comparison(subset, paired_only=False)
    st.markdown("### Aggregated comparison")
    visible = [{"Scenario": r["scenario"], "Algorithm": r["algorithm"],
        "Runs": r["run_count"], "Successful": r["successful_runs"], "Failed": r["failed_runs"],
        "Latency (ms)": r["mean_latency_ms"], "Latency samples": r["mean_latency_ms_valid_samples"],
        "Latency 95% CI": _ci(r, "mean_latency_ms"), "Median latency (ms)": r["mean_latency_ms_median"],
        "p95 latency (ms)": _metric_mean(subset, r["scenario"], r["algorithm"], "p95_latency_ms"),
        "PDR": r["pdr"], "Throughput (Mbps)": r["effective_throughput_mbps"],
        "Loss rate": r["packet_loss_rate"], "Drop rate": r["drop_rate"], "Timeout rate": r["timeout_rate"],
        "Mean hops": r["mean_hop_count"], "Reroutes": r["reroutes"],
        "Recovery successes": _metric_mean(subset, r["scenario"], r["algorithm"], "recovery_successes"),
        "Recovery time (ms)": r["mean_recovery_time_ms"], "Fog queue (ms)": r["mean_fog_queue_delay_ms"],
        "Fog utilization": r["mean_fog_utilization"], "Wall runtime (s)": r["wall_clock_runtime_s"],
        "Notes": r.get("notes")} for r in summary]
    st.dataframe(visible, use_container_width=True, hide_index=True)
    st.caption("Latency is delivered-only; PDR denominator includes pending among all generated packets. CI is exploratory and small seed counts do not establish significance. Null values are undefined or unavailable.")
    for metric, title, unit in (("mean_latency_ms", "Mean latency by scenario", "ms"),
        ("pdr", "Packet delivery ratio", "ratio"),
        ("effective_throughput_mbps", "Delivered payload throughput", "Mbps"),
        ("mean_recovery_time_ms", "Successful route recovery time", "ms")):
        figure = experiment_chart(subset, metric, title, unit)
        if figure:
            st.plotly_chart(figure, use_container_width=True)
    st.markdown("### Paired differences")
    st.caption("Difference = multi_factor minus shortest_latency. Only common seeds with both completed arms and non-null metric values are included.")
    paired_rows = paired["summary"]
    if paired_rows:
        st.dataframe(paired_rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No matched two-algorithm seed pairs remain after filtering.")


def _ci(row, metric):
    low, high = row.get(f"{metric}_ci95_low"), row.get(f"{metric}_ci95_high")
    return None if low is None or high is None else f"[{low:.4g}, {high:.4g}]"


def _metric_mean(rows, scenario, algorithm, metric):
    vals = [(r.get("metrics") or {}).get(metric) for r in rows
        if r.get("scenario") == scenario and r.get("algorithm") == algorithm and r.get("status") == "completed"]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None
