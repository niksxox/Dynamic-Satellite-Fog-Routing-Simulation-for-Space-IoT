from __future__ import annotations

import plotly.express as px


def experiment_chart(rows, metric, title, unit):
    data = []
    for row in rows:
        if row.get("status") != "completed":
            continue
        value = (row.get("metrics") or {}).get(metric)
        if value is not None:
            data.append({"Scenario": row.get("scenario"), "Algorithm": row.get("algorithm"),
                         "Seed": row.get("seed"), "Value": value})
    if not data:
        return None
    fig = px.box(data, x="Scenario", y="Value", color="Algorithm", points="all", hover_data=["Seed"],
                 title=title, labels={"Value": unit})
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0b1724", plot_bgcolor="#0b1724")
    return fig
