from __future__ import annotations

from collections import defaultdict
from math import sqrt
from statistics import mean, median, stdev

METRICS = ("mean_latency_ms", "pdr", "effective_throughput_mbps", "mean_recovery_time_ms",
           "reroutes", "packet_loss_rate", "drop_rate", "timeout_rate", "mean_hop_count",
           "mean_fog_utilization", "mean_fog_queue_delay_ms", "wall_clock_runtime_s")
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 15: 2.131, 20: 2.086, 30: 2.042}


def _critical(df):
    return next((_T95[k] for k in sorted(_T95) if df <= k), 1.96)


def _summary(values):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"valid_samples": 0, "mean": None, "stddev": None, "median": None, "ci95_low": None, "ci95_high": None}
    avg = mean(vals)
    sd = stdev(vals) if len(vals) > 1 else None
    margin = _critical(len(vals)-1) * sd / sqrt(len(vals)) if sd is not None else None
    return {"valid_samples": len(vals), "mean": avg, "stddev": sd, "median": median(vals),
            "ci95_low": avg-margin if margin is not None else None,
            "ci95_high": avg+margin if margin is not None else None}


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["scenario"], row["algorithm"])].append(row)
    output = []
    for (scenario, algorithm), members in sorted(groups.items()):
        valid = [r for r in members if r["status"] == "completed"]
        record = {"scenario": scenario, "algorithm": algorithm, "run_count": len(members),
                  "successful_runs": len(valid), "failed_runs": len(members)-len(valid)}
        for metric in METRICS:
            summary = _summary([r.get("metrics", {}).get(metric) for r in valid])
            record[metric] = summary["mean"]
            record[f"{metric}_valid_samples"] = summary["valid_samples"]
            record[f"{metric}_stddev"] = summary["stddev"]
            record[f"{metric}_median"] = summary["median"]
            record[f"{metric}_ci95_low"] = summary["ci95_low"]
            record[f"{metric}_ci95_high"] = summary["ci95_high"]
        record["notes"] = "; ".join(sorted({r.get("error") for r in members if r.get("error")}))
        output.append(record)
    return output


def paired_differences(rows):
    pairs = defaultdict(dict)
    for row in rows:
        if row["status"] == "completed":
            pairs[(row["scenario"], row["seed"])][row["algorithm"]] = row.get("metrics", {})
    output = []
    for (scenario, seed), algorithms in sorted(pairs.items()):
        if "shortest_latency" not in algorithms or "multi_factor" not in algorithms:
            continue
        for metric in METRICS:
            baseline = algorithms["shortest_latency"].get(metric)
            proposed = algorithms["multi_factor"].get(metric)
            if baseline is None or proposed is None:
                continue
            output.append({"scenario": scenario, "seed": seed, "metric": metric,
                           "difference_multi_factor_minus_baseline": proposed-baseline})
    summaries = []
    by_metric = defaultdict(list)
    for row in output:
        by_metric[(row["scenario"], row["metric"])].append(row["difference_multi_factor_minus_baseline"])
    for (scenario, metric), vals in sorted(by_metric.items()):
        summaries.append({"scenario": scenario, "metric": metric, "paired_samples": len(vals),
                          "mean_difference": mean(vals), "stddev": stdev(vals) if len(vals)>1 else None,
                          "ci_method": "paired t interval (95%, small-sample t critical values; exploratory)",
                          "ci95_low": _summary(vals)["ci95_low"],
                          "ci95_high": _summary(vals)["ci95_high"]})
    return {"per_seed": output, "summary": summaries}
