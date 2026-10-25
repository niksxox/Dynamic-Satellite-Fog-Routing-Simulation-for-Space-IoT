from __future__ import annotations

import plotly.graph_objects as go


SYMBOLS = {"iot": "circle", "satellite": "diamond", "ground_station": "square",
           "fog": "hexagon", "cloud": "star"}
COLORS = {"iot": "#45c1d1", "satellite": "#7d8cff", "ground_station": "#ffc857",
          "fog": "#9c7be8", "cloud": "#f47c69"}


def _node_data(node):
    if isinstance(node, dict):
        cfg = node.get("configuration", node)
        pos = cfg.get("position", {})
        return node.get("node_id", cfg.get("node_id", "?")), node.get("node_type", cfg.get("node_type", "?")), pos, cfg
    pos = node.position
    return node.node_id, node.node_type.value, {"x_km": pos.x_km, "y_km": pos.y_km}, {
        "operational": node.operational, "communication_range_km": node.communication_range_km,
        "bandwidth_mbps": node.bandwidth_mbps, "processing_delay_ms": node.processing_delay_ms,
        "processing_capacity_pps": node.processing_capacity_pps,
        "packet_generation_rate_pps": node.packet_generation_rate_pps,
        "default_packet_size_bytes": node.default_packet_size_bytes,
        "destination": node.destination}


def _edge_data(edge):
    if len(edge) == 3:
        source, target, attrs = edge
        return source, target, attrs
    return edge.get("source"), edge.get("target"), edge.get("configuration", edge)


def network_figure(nodes, links, selected_path=(), selected_event=None):
    figure = go.Figure()
    coords = {}
    node_rows = []
    for node in nodes:
        node_id, node_type, pos, cfg = _node_data(node)
        x, y = pos.get("x_km"), pos.get("y_km")
        if x is None or y is None:
            continue
        coords[node_id] = (x, y)
        node_rows.append((node_id, node_type, x, y, cfg))
    selected_edges = {frozenset((a, b)) for a, b in zip(selected_path, selected_path[1:])}
    for edge in links:
        source, target, attrs = _edge_data(edge)
        if source not in coords or target not in coords:
            continue
        active = bool(attrs.get("operational", True))
        highlighted = frozenset((source, target)) in selected_edges
        color = "#2bd49b" if active else "#ee5260"
        width = 4 if highlighted else 1.5
        x1, y1 = coords[source]; x2, y2 = coords[target]
        state = attrs.get("dashboard_state", "active" if active else "failed/unavailable")
        details = (f"{source} ↔ {target}<br>State: {state}<br>"
            f"Bandwidth: {attrs.get('bandwidth_mbps', 'unavailable')} Mbps<br>"
            f"Propagation: {attrs.get('propagation_latency_ms', 'unavailable')} ms<br>"
            f"Packet loss: {attrs.get('packet_loss_probability', 'unavailable')}")
        figure.add_trace(go.Scatter(x=[x1, x2, None], y=[y1, y2, None], mode="lines",
            line={"color": color, "width": width, "dash": "solid" if active else "dash"},
            hoverinfo="text", text=[details, details, ""], showlegend=False))
    if selected_event:
        source, target = selected_event.get("source"), selected_event.get("target")
        if source in coords and target in coords:
            x1, y1 = coords[source]; x2, y2 = coords[target]
            figure.add_trace(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line={"color": "#ffffff", "width": 7, "dash": "dot"},
                name="Selected event", hoverinfo="skip"))
        node_id = selected_event.get("affected_node")
        if node_id in coords:
            x, y = coords[node_id]
            figure.add_trace(go.Scatter(x=[x], y=[y], mode="markers", name="Affected node",
                marker={"symbol": "circle-open", "size": 34, "color": "#ffffff", "line": {"width": 3}},
                hovertemplate=f"Affected node: {node_id}<extra></extra>"))
    path_nodes = set(selected_path)
    for node_type in sorted({row[1] for row in node_rows}):
        group = [row for row in node_rows if row[1] == node_type]
        figure.add_trace(go.Scatter(x=[r[2] for r in group], y=[r[3] for r in group],
            mode="markers+text", text=[r[0] for r in group], textposition="top center",
            name=node_type.replace("_", " ").title(),
            marker={"symbol": SYMBOLS.get(node_type, "circle"), "size": 19,
                "color": ["#ffffff" if r[0] in path_nodes else COLORS.get(node_type, "#cccccc") for r in group],
                "line": {"color": COLORS.get(node_type, "#cccccc"), "width": 2}},
            customdata=[str(r[4]) for r in group], hovertemplate="%{text}<br>Type: " + node_type + "<br>%{customdata}<extra></extra>"))
    figure.update_layout(template="plotly_dark", height=520, margin={"l": 10, "r": 10, "t": 25, "b": 10},
        xaxis_title="X position (km)", yaxis_title="Y position (km)",
        legend={"orientation": "h", "y": -0.15}, plot_bgcolor="#0b1724", paper_bgcolor="#0b1724",
        xaxis={"gridcolor": "#21364a"}, yaxis={"gridcolor": "#21364a", "scaleanchor": "x", "scaleratio": 1})
    return figure
