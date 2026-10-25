from __future__ import annotations

import csv
import io
import json

import streamlit as st
from dashboard.utils.errors import storage_error

from dashboard.services.data import load_local_experiments


def render(repository=None):
    st.markdown("## Experiment history")
    experiments = list(st.session_state.get("dashboard_experiments", []))
    for bundle in load_local_experiments():
        if not any(e.get("experiment_id") == bundle.get("experiment_id") for e in experiments):
            experiments.append(bundle)
    if repository:
        try:
            for item in repository.list_experiments(100):
                detail = repository.get_experiment_detail(item["experiment_id"])
                if detail and not any(e.get("experiment_id") == detail.get("experiment_id") for e in experiments):
                    detail["storage"] = "postgresql"
                    experiments.append(detail)
        except Exception as exc:
            st.warning(f"Could not read PostgreSQL experiment history: {storage_error(exc)}")
    if not experiments:
        st.info("No experiment records found. Run an experiment in Simulation Lab or choose PostgreSQL storage to inspect persisted experiments.")
        return
    experiments.sort(key=lambda e: e.get("experiment_id", ""), reverse=True)
    ids = [e.get("experiment_id") for e in experiments]
    selected_id = st.selectbox("Experiment", ids)
    bundle = next(e for e in experiments if e.get("experiment_id") == selected_id)
    rows = bundle.get("rows", [])
    st.write(f"Status: **{bundle.get('status', 'unknown')}** · scenario `{bundle.get('scenario', 'stored configuration')}` · "
        f"storage `{bundle.get('storage', 'local export')}`")
    st.json(bundle.get("configuration", {}))
    if rows:
        st.dataframe([{**{k: row.get(k) for k in ("scenario", "algorithm", "seed", "run_id", "status", "error", "expected_event_applied")},
            "PDR": (row.get("metrics") or {}).get("pdr"),
            "Latency (ms)": (row.get("metrics") or {}).get("mean_latency_ms"),
            "Throughput (Mbps)": (row.get("metrics") or {}).get("effective_throughput_mbps")}
            for row in rows], use_container_width=True, hide_index=True)
        failed = [r for r in rows if r.get("status") != "completed"]
        if failed:
            st.markdown("### Failed runs")
            st.dataframe([{"run_id": r.get("run_id"), "algorithm": r.get("algorithm"),
                "seed": r.get("seed"), "error": r.get("error")} for r in failed], use_container_width=True, hide_index=True)
    json_bytes = json.dumps(bundle, indent=2, allow_nan=False, default=str).encode()
    st.download_button("Download experiment JSON", json_bytes,
        file_name=f"{selected_id}.json", mime="application/json")
    if rows:
        csv_rows = []
        for row in rows:
            csv_rows.append({**{k: row.get(k) for k in ("scenario", "algorithm", "seed", "run_id", "status", "error")},
                             **(row.get("metrics") or {})})
        st.download_button("Download per-run metrics CSV", _csv(csv_rows),
            file_name=f"{selected_id}_per_run.csv", mime="text/csv")
    run_options = [r.get("run_id") for r in rows if r.get("run_id")]
    if repository and run_options:
        run_id = st.selectbox("Inspect persisted packet and route history", run_options)
        try:
            packets = repository.get_packet_history(run_id)
            st.dataframe([{"packet_id": p.packet_id, "source": p.source, "destination": p.destination,
                "state": p.final_state, "generated_at_s": p.generated_at_s,
                "hops": p.hop_count, "reroutes": p.reroute_count, "final_path": p.final_path}
                for p in packets], use_container_width=True, hide_index=True)
            packet_ids = [p.packet_id for p in packets]
            if packet_ids:
                packet_id = st.selectbox("Packet", packet_ids)
                routes = repository.get_route_history(run_id, packet_id)
                st.dataframe([{"selected_at_s": r.selected_at_s, "cause": r.cause,
                    "algorithm": r.algorithm, "path": r.path, "available": r.available}
                    for r in routes], use_container_width=True, hide_index=True)
        except Exception as exc:
            st.warning(f"Historical packet retrieval failed: {storage_error(exc)}")
    elif rows and bundle.get("storage") != "postgresql":
        st.caption("Local experiment exports contain per-run metrics and configuration, not full packet traces. Those detailed histories were only retained in the simulation session unless PostgreSQL persistence was selected.")


def _csv(rows):
    if not rows:
        return ""
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=sorted({k for r in rows for k in r}), extrasaction="ignore")
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue().encode()
