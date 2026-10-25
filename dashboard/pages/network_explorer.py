from __future__ import annotations

import streamlit as st

from dashboard.components.network_view import network_figure
from dashboard.utils.errors import storage_error


def render(repository=None):
    st.markdown("## Network explorer")
    local = st.session_state.get("dashboard_runs", {})
    options = list(local)
    persisted = []
    if repository:
        try:
            persisted = [r["run_id"] for r in repository.list_runs(100)]
            options += [run_id for run_id in persisted if run_id not in options]
        except Exception as exc:
            st.warning(f"Could not read run index: {storage_error(exc)}")
    if not options:
        st.info("No run topology is available. Run a simulation first, or configure PostgreSQL storage for persisted runs.")
        return
    run_id = st.selectbox("Simulation run", options, key="network_run")
    local_result = local.get(run_id)
    if local_result:
        nodes = local_result.node_configurations
        links = _include_unavailable(local_result.initial_link_configurations,
                                     local_result.current_link_configurations)
        packets = local_result.packets
        events = local_result.events
        decisions = local_result.routing_decisions
        run_desc = f"{local_result.routing_mode} · seed {local_result.config.seed} · end state at {local_result.end_time_s:g}s"
    elif repository:
        try:
            network = repository.get_network_configuration(run_id)
            nodes, links = network["nodes"], network["links"]
            packets = repository.get_packet_history(run_id)
            events = repository.get_event_timeline(run_id)
            decisions = []
            run_desc = "Persisted configuration and final link state; historical positions are unavailable."
        except Exception as exc:
            st.error(f"Unable to load persisted run: {storage_error(exc)}")
            return
    else:
        return
    st.caption(run_desc)
    packet_ids = [p.packet_id if hasattr(p, "packet_id") else p.get("packet_id") for p in packets]
    packet_id = st.selectbox("Packet route", ["(none)"] + packet_ids, key="network_packet") if packet_ids else "(none)"
    packet = next((p for p in packets if (p.packet_id if hasattr(p, "packet_id") else p.get("packet_id")) == packet_id), None)
    path = []
    if packet:
        path = packet.path if hasattr(packet, "path") else packet.final_path
    st.plotly_chart(network_figure(nodes, links, path), use_container_width=True)
    node_ids = [n.node_id if hasattr(n, "node_id") else n.get("node_id") for n in nodes]
    link_keys = [f"{e[0]} ↔ {e[1]}" if isinstance(e, tuple) else f"{e['source']} ↔ {e['target']}" for e in links]
    node_id = st.selectbox("Inspect node", ["(none)"] + node_ids, key="network_node") if node_ids else "(none)"
    link_id = st.selectbox("Inspect link", ["(none)"] + link_keys, key="network_link") if link_keys else "(none)"
    col1, col2 = st.columns(2)
    with col1:
        if node_id != "(none)":
            node = next(n for n in nodes if (n.node_id if hasattr(n, "node_id") else n.get("node_id")) == node_id)
            if isinstance(node, dict):
                st.json(node)
            else:
                st.json({"node_id": node.node_id, "type": node.node_type.value,
                    "operational": node.operational, "position_km": {"x": node.position.x_km, "y": node.position.y_km},
                    "range_km": node.communication_range_km, "bandwidth_mbps": node.bandwidth_mbps,
                    "traffic_rate_pps": node.packet_generation_rate_pps,
                    "processing_delay_ms": node.processing_delay_ms})
    with col2:
        if link_id != "(none)":
            selected = next(e for e in links if (f"{e[0]} ↔ {e[1]}" if isinstance(e, tuple) else f"{e['source']} ↔ {e['target']}") == link_id)
            st.json(selected[2] if isinstance(selected, tuple) else selected)
    if packet:
        st.markdown("### Selected packet")
        st.write({"packet_id": packet.packet_id if hasattr(packet, "packet_id") else packet.packet_id,
            "source": packet.source, "destination": packet.destination,
            "state": packet.state.value if hasattr(getattr(packet, "state", None), "value") else packet.final_state,
            "path": path, "hops": packet.hop_count, "reroutes": packet.reroute_count})
        packet_routes = [d for d in decisions if d.packet_id == packet_id]
        if packet_routes:
            st.dataframe([{"time_s": d.timestamp_s, "cause": d.cause,
                "algorithm": d.algorithm, "available": d.available, "path": list(d.path),
                "recovery_ms": None if d.recovery_time_s is None else d.recovery_time_s * 1000}
                for d in packet_routes], use_container_width=True, hide_index=True)
    st.caption("The graph shows the last captured topology state and actual packet path. The simulator does not record timestamped node-position snapshots for a faithful historical animation.")


def _include_unavailable(initial, current):
    current_keys = {frozenset((a, b)) for a, b, _ in current}
    combined = list(current)
    for a, b, attrs in initial:
        if frozenset((a, b)) not in current_keys:
            unavailable = dict(attrs)
            unavailable["operational"] = False
            unavailable["dashboard_state"] = "not present in captured final topology"
            combined.append((a, b, unavailable))
    return combined
