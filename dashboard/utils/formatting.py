def format_metric(value, unit="", precision=3):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{precision}f}{(' ' + unit) if unit else ''}"
    return f"{value}{(' ' + unit) if unit else ''}"


def compatible_rows(rows):
    """Keep only scenario/config groups containing both algorithms with matched seeds."""
    from collections import defaultdict
    groups = defaultdict(dict)
    for row in rows:
        if row.get("status") in {"completed", "failed"}:
            groups[(row.get("scenario"), row.get("seed"), _freeze(row.get("configuration")))][row.get("algorithm")] = row
    keep = []
    for pair in groups.values():
        if {"shortest_latency", "multi_factor"} <= set(pair):
            keep.extend(pair.values())
    return keep


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value
