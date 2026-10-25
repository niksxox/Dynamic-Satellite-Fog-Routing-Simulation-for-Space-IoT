from __future__ import annotations

import csv
import json
from pathlib import Path

from src.experiments.comparison import aggregate, paired_differences


def export_experiment(bundle, output_dir):
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    rows = bundle["rows"]
    summary = aggregate(rows)
    paired = paired_differences(rows)
    bundle["aggregates"] = summary
    bundle["paired_comparison"] = paired
    (folder / f"{bundle['experiment_id']}.json").write_text(json.dumps(bundle, indent=2, allow_nan=False), encoding="utf-8")
    _write_csv(folder / f"{bundle['experiment_id']}_per_run.csv", rows)
    _write_csv(folder / f"{bundle['experiment_id']}_comparison.csv", summary)
    _write_csv(folder / f"{bundle['experiment_id']}_paired_differences.csv", paired["per_seed"])
    (folder / f"{bundle['experiment_id']}_report.md").write_text(_markdown(bundle, summary, paired), encoding="utf-8")
    _charts(bundle, summary, folder)
    return bundle


def _write_csv(path, rows):
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True, allow_nan=False)
                             if isinstance(value, (dict, list, tuple)) else value
                             for key, value in row.items()})


def _markdown(bundle, summary, paired):
    lines = [f"# Experiment {bundle['experiment_id']}", "", f"Scenario: `{bundle['scenario']}` — {bundle['definition']}",
        f"Status: **{bundle['status']}**; storage: `{bundle['storage']}`; elapsed: {bundle['wall_clock_duration_s']:.3f}s", "",
        "| Scenario | Algorithm | Successful / failed | Mean latency (ms) | PDR | Throughput (Mbps) | Recovery (ms) | Reroutes | Latency 95% CI |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in summary:
        lines.append(f"| {row['scenario']} | {row['algorithm']} | {row['successful_runs']} / {row['failed_runs']} | "
            f"{_fmt(row['mean_latency_ms'])} | {_fmt(row['pdr'])} | {_fmt(row['effective_throughput_mbps'])} | "
            f"{_fmt(row['mean_recovery_time_ms'])} | {_fmt(row['reroutes'])} | "
            f"{_fmt(row['mean_latency_ms_ci95_low'])}–{_fmt(row['mean_latency_ms_ci95_high'])} (n={row['mean_latency_ms_valid_samples']}) |")
    lines += ["", "Paired differences are multi-factor minus shortest-latency. The small-sample t intervals are exploratory and do not establish significance.",
        "", "Failed runs remain in the per-run export and are counted above. Null metrics mean unavailable or undefined, never zero.",
        "", "## Metric and model notes", "", bundle["metric_definitions"]["mean_latency_ms"],
        "", "Route-computation CPU time and time-integrated active-link availability are unavailable in current instrumentation. Satellite movement is the existing deterministic circular projection, not orbital mechanics.", ""]
    return "\n".join(lines)


def _fmt(value):
    return "—" if value is None else f"{value:.5g}" if isinstance(value, (float, int)) else str(value)


def _charts(bundle, summary, folder):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return
    plots = [("mean_latency_ms", "Mean delivered latency (ms)"), ("pdr", "Packet delivery ratio"),
             ("effective_throughput_mbps", "Delivered-payload throughput (Mbps)"),
             ("mean_recovery_time_ms", "Mean successful recovery time (ms)")]
    for metric, title in plots:
        rows = [r for r in summary if r.get(metric) is not None]
        if not rows:
            continue
        fig = go.Figure()
        for algorithm in sorted({r["algorithm"] for r in rows}):
            selected = [r for r in rows if r["algorithm"] == algorithm]
            fig.add_bar(name=algorithm, x=[r["scenario"] for r in selected],
                y=[r[metric] for r in selected],
                error_y={"type": "data", "symmetric": False,
                    "array": [max(0, (r.get(f"{metric}_ci95_high") or r[metric])-r[metric]) for r in selected],
                    "arrayminus": [max(0, r[metric]-(r.get(f"{metric}_ci95_low") or r[metric])) for r in selected]},
                text=[f"n={r[f'{metric}_valid_samples']}" for r in selected])
        fig.update_layout(title=title, xaxis_title="Scenario", yaxis_title=title,
                          barmode="group", template="plotly_white")
        fig.write_html(folder / f"{bundle['experiment_id']}_{metric}.html", include_plotlyjs="cdn")
