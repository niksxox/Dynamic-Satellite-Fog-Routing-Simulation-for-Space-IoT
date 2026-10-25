from __future__ import annotations

from copy import deepcopy

import streamlit as st

from dashboard.components.network_view import network_figure
from dashboard.utils.errors import storage_error
from src.topology.engine import TopologyEngine


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
        if local_result.config.orbital_model == "circular_two_body":
            selected_time = st.slider("Virtual simulation time (s)", 0.0,
                float(local_result.end_time_s), float(local_result.end_time_s), step=float(local_result.config.topology_update_interval_s), key="network_time")
            engine = TopologyEngine(local_result.config)
            replay_nodes = deepcopy(local_result.node_configurations)
            engine.initialize_network(replay_nodes, 0.0)
            replay_events = sorted(local_result.events, key=lambda e: e.timestamp_s)
            for event in replay_events:
                if event.timestamp_s > selected_time:
                    break
                if event.event_type in {"link_failure", "link_recovery"} and event.source and event.target:
                    engine.set_link_operational(event.source, event.target,
                        event.event_type == "link_recovery", event.timestamp_s)
                elif event.event_type in {"node_failure", "node_recovery", "fog_overload", "fog_recovery"} and event.affected_node:
                    engine.set_node_operational(event.affected_node,
                        event.event_type in {"node_recovery", "fog_recovery"}, event.timestamp_s)
            engine.update_topology(float(selected_time))
            nodes = replay_nodes
            links = [(a, b, dict(attrs)) for a, b, attrs in engine.graph.edges(data=True)]
            run_desc += f" · geometry recomputed at {selected_time:g}s"
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
    st.caption("Circular two-body views recompute geometry at the selected virtual time from stored orbit inputs and recorded failure/recovery events. The plot is a 2D ECI X/Y projection, not a validated ephemeris or a full 3D globe.")


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
