from __future__ import annotations

import streamlit as st

from dashboard.components.network_view import network_figure
from dashboard.services.data import events_as_dicts
from dashboard.pages.network_explorer import _include_unavailable
from dashboard.utils.errors import storage_error


def render(repository=None):
    st.markdown("## Failure replay & event timeline")
    local = st.session_state.get("dashboard_runs", {})
    options = list(local)
    if repository:
        try:
            options += [r["run_id"] for r in repository.list_runs(100) if r["run_id"] not in options]
        except Exception as exc:
            st.warning(f"Could not load persisted run index: {storage_error(exc)}")
    if not options:
        st.info("No simulation event history is available yet.")
        return
    run_id = st.selectbox("Run to replay", options, key="replay_run")
    result = local.get(run_id)
    if result:
        events = events_as_dicts(result.events)
        nodes = result.node_configurations
        links = _include_unavailable(result.initial_link_configurations,
                                     result.current_link_configurations)
        packets = result.packets
        routes = result.routing_decisions
    elif repository:
        try:
            events = events_as_dicts(repository.get_event_timeline(run_id))
            network = repository.get_network_configuration(run_id)
            nodes, links = network["nodes"], network["links"]
            packets, routes = repository.get_packet_history(run_id), []
        except Exception as exc:
            st.error(f"Unable to load persisted timeline: {storage_error(exc)}")
            return
    else:
        return
    st.caption("Events are ordered by virtual simulation seconds. Without timestamped position/topology snapshots, this view highlights recorded events on the last captured topology; it does not animate orbital state.")
    if not events:
        st.info("This run has no recorded events.")
    else:
        table = [{"Time (s)": e.get("timestamp_s"), "Event": e.get("event_type"),
            "Node": e.get("affected_node"), "Link": _link(e), "Packet": e.get("packet_id"),
            "Description": e.get("description")} for e in events]
        st.dataframe(table, use_container_width=True, hide_index=True)
        labels = [f"{e.get('timestamp_s', 0):.6f}s · {e.get('event_type')} · {e.get('description', '')}" for e in events]
        chosen = st.selectbox("Inspect event", range(len(events)), format_func=lambda i: labels[i], key="replay_event")
        event = events[chosen]
        event_packet = next((p for p in packets if (p.packet_id if hasattr(p, "packet_id") else p.packet_id) == event.get("packet_id")), None) if event.get("packet_id") else None
        event_path = (event_packet.path if hasattr(event_packet, "path") else event_packet.final_path) if event_packet else ()
        st.plotly_chart(network_figure(nodes, links, selected_path=event_path,
                                       selected_event=event), use_container_width=True)
        st.json(event)
    packet_ids = [p.packet_id if hasattr(p, "packet_id") else p["packet_id"] for p in packets]
    if packet_ids:
        packet_id = st.selectbox("Packet route history", packet_ids, key="replay_packet")
        packet = next(p for p in packets if (p.packet_id if hasattr(p, "packet_id") else p["packet_id"]) == packet_id)
        path = packet.path if hasattr(packet, "path") else packet.final_path
        st.markdown(f"**{packet_id}:** `{' → '.join(path)}`")
        packet_routes = [r for r in routes if r.packet_id == packet_id]
        if not packet_routes and repository and not result:
            packet_routes = repository.get_route_history(run_id, packet_id)
        if packet_routes:
            rows = []
            for r in packet_routes:
                rows.append({"Time (s)": getattr(r, "timestamp_s", getattr(r, "selected_at_s", None)),
                    "Cause": r.cause, "Algorithm": r.algorithm,
                    "Path": list(r.path), "Available": getattr(r, "available", True),
                    "Recovery (ms)": None if getattr(r, "recovery_time_s", None) is None else r.recovery_time_s * 1000})
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No route-decision records are available for this packet.")


def _link(event):
    source, target = event.get("source"), event.get("target")
    return f"{source} ↔ {target}" if source and target else None
