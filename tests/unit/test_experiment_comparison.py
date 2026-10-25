from src.experiments.comparison import aggregate, paired_differences


def test_aggregation_counts_failures_and_reports_sample_variability():
    rows = [
        {"scenario": "s", "algorithm": "shortest_latency", "seed": 1,
         "status": "completed", "metrics": {"pdr": 0.5}},
        {"scenario": "s", "algorithm": "shortest_latency", "seed": 2,
         "status": "completed", "metrics": {"pdr": 1.0}},
        {"scenario": "s", "algorithm": "shortest_latency", "seed": 3,
         "status": "failed", "error": "failed"},
    ]
    summary = aggregate(rows)[0]
    assert summary["successful_runs"] == 2
    assert summary["failed_runs"] == 1
    assert summary["pdr_valid_samples"] == 2
    assert summary["pdr"] == 0.75
    assert summary["pdr_ci95_low"] is not None


def test_paired_comparison_uses_only_matching_completed_seeds():
    rows = []
    for algo, val in (("shortest_latency", 5), ("multi_factor", 3)):
        rows.append({"scenario": "s", "seed": 7, "algorithm": algo,
                     "status": "completed", "metrics": {"mean_latency_ms": val}})
    result = paired_differences(rows)
    assert result["per_seed"][0]["difference_multi_factor_minus_baseline"] == -2
    assert result["summary"][0]["paired_samples"] == 1


def test_missing_metric_is_null_with_zero_valid_samples():
    row = {"scenario": "s", "algorithm": "x", "status": "completed", "metrics": {}}
    summary = aggregate([row])[0]
    assert summary["mean_latency_ms"] is None
    assert summary["mean_latency_ms_valid_samples"] == 0
