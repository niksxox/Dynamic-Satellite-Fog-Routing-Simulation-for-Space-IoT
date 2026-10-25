from __future__ import annotations

import json
from pathlib import Path

from src.experiments.comparison import aggregate, paired_differences


def load_local_experiments(root="experiment_output"):
    output = []
    for path in sorted(Path(root).glob("**/exp-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
            bundle["source_file"] = str(path)
            output.append(bundle)
        except (OSError, json.JSONDecodeError):
            continue
    return output


def events_as_dicts(events):
    rows = []
    for event in events:
        if isinstance(event, dict):
            rows.append(event)
        else:
            rows.append({"event_id": getattr(event, "event_id", ""),
                "timestamp_s": getattr(event, "timestamp_s", 0),
                "event_type": getattr(event, "event_type", "unknown"),
                "affected_node": getattr(event, "affected_node", None),
                "source": getattr(event, "source", None), "target": getattr(event, "target", None),
                "packet_id": getattr(event, "packet_id", None),
                "description": getattr(event, "description", ""),
                "metadata": getattr(event, "details", getattr(event, "metadata_json", {}))})
    return sorted(rows, key=lambda e: e.get("timestamp_s", 0))


def all_experiment_rows(bundles):
    return [row for bundle in bundles for row in bundle.get("rows", [])]


def filtered_comparison(rows, scenario=None, algorithm=None, seed=None, paired_only=False):
    selected = [r for r in rows if (scenario is None or r.get("scenario") == scenario)
        and (algorithm is None or r.get("algorithm") == algorithm)
        and (seed is None or r.get("seed") == seed)]
    if paired_only:
        from dashboard.utils.formatting import compatible_rows
        selected = compatible_rows(selected)
    return aggregate(selected), paired_differences(selected), selected
