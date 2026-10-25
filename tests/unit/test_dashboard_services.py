import pytest

from dashboard.services.data import events_as_dicts, filtered_comparison
from dashboard.services.storage import open_repository
from dashboard.services.simulation import run_simulation
from dashboard.utils.formatting import compatible_rows, format_metric


def test_formatting_preserves_undefined_metrics():
    assert format_metric(None, "ms") == "—"
    assert format_metric(1.2345, "ms", 2) == "1.23 ms"


def test_compatibility_filter_requires_both_algorithms_same_config_and_seed():
    rows = []
    for algo in ("shortest_latency", "multi_factor"):
        rows.append({"scenario": "stable_topology", "seed": 7, "algorithm": algo,
            "status": "completed", "configuration": {"same": True}})
    rows.append({"scenario": "stable_topology", "seed": 8, "algorithm": "shortest_latency",
        "status": "completed", "configuration": {"same": True}})
    rows.append({"scenario": "stable_topology", "seed": 9, "algorithm": "multi_factor",
        "status": "completed", "configuration": {"same": False}})
    compatible = compatible_rows(rows)
    assert len(compatible) == 2
    assert {r["seed"] for r in compatible} == {7}


def test_simulation_service_runs_actual_failure_and_orders_events():
    result, meta = run_simulation("inter_satellite_link_failure", "shortest_latency",
        seed=11, duration_s=1.0, satellite_count=3, traffic_intensity=30)
    assert result.packets
    assert meta["expected_event_applied"] is True
    assert [e.timestamp_s for e in result.events] == sorted(e.timestamp_s for e in result.events)
    assert result.initial_link_configurations
    assert result.current_link_configurations


def test_local_storage_is_explicit_and_database_missing_error_is_actionable(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert open_repository("local") is None
    with pytest.raises(RuntimeError, match="DATABASE_URL is missing"):
        open_repository("postgres")


def test_experiment_filter_returns_no_paired_claim_for_incompatible_rows():
    rows = [{"scenario": "s", "seed": 1, "algorithm": "shortest_latency",
             "status": "completed", "configuration": {}, "metrics": {"pdr": 1}}]
    summary, paired, selected = filtered_comparison(rows, paired_only=True)
    assert summary == [] and paired["summary"] == [] and selected == []


def test_events_adapter_orders_events_from_actual_simulation_records():
    result, _ = run_simulation("stable_topology", "multi_factor", 2, 0.5, 2, 100)
    rows = events_as_dicts(result.events)
    assert rows == sorted(rows, key=lambda e: e["timestamp_s"])
