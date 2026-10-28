from datetime import datetime, timezone

import numpy as np

from app.tracking import (
    SatelliteTracker,
    parse_alternate_tle_records,
    parse_tle_records,
    position_to_geodetic,
    propagate_positions,
)


ISS_TLE_PAYLOAD = [
    {
        "OBJECT_NAME": "ISS (ZARYA)",
        "NORAD_CAT_ID": 25544,
        "EPOCH": "2021-10-02T12:14:29.000000",
        "TLE_LINE1": "1 25544U 98067A   21275.51005787  .00001490  00000-0  33219-4 0  9990",
        "TLE_LINE2": "2 25544  51.6442 209.3537 0003886  69.1842  47.1808 15.48815329305128",
    }
]


def test_tle_propagation_returns_earth_fixed_position():
    satellites = parse_tle_records(ISS_TLE_PAYLOAD)
    position = propagate_positions(
        satellites, datetime(2021, 10, 2, 12, 14, 29, tzinfo=timezone.utc)
    )

    assert position.shape == (1, 3)
    latitude, longitude, altitude = position_to_geodetic(position[0])
    assert -52.0 <= latitude <= 52.0
    assert -180.0 <= longitude <= 180.0
    assert 300.0 <= altitude <= 500.0


def test_tracker_ground_track_contains_one_orbit_and_catalog_identity():
    tracker = SatelliteTracker()
    tracker._satellites = parse_tle_records(ISS_TLE_PAYLOAD)

    result = tracker.ground_track(
        0, datetime(2021, 10, 2, 12, 14, 29, tzinfo=timezone.utc)
    )

    assert result["norad_id"] == 25544
    assert result["name"] == "ISS (ZARYA)"
    assert len(result["track"]) > 80
    assert result["track"][0] != result["track"][-1]


def test_engine_live_position_provider_updates_output_and_survives_reset():
    from app.sim.engine import Engine

    engine = Engine(seed=42)
    positions = np.tile(np.array([[7000.0, 0.0, 0.0]]), (120, 1))
    engine.set_position_provider(lambda _: positions)

    frame = engine.step(0.1)
    assert frame["positionSource"] == "tle"
    assert all(620.0 <= satellite["alt"] <= 640.0 for satellite in frame["sats"])

    engine.apply_command("reset")
    assert engine.step(0.1)["positionSource"] == "tle"


def test_alternate_provider_keeps_only_recent_starlink_records():
    now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    current = {
        "member": [
            {
                "satelliteId": 25544,
                "name": "STARLINK-TEST",
                "date": "2026-10-27T11:00:00Z",
                "line1": "1 25544U 98067A   21275.51005787  .00001490  00000-0  33219-4 0  9990",
                "line2": "2 25544  51.6442 209.3537 0003886  69.1842  47.1808 15.48815329305128",
            },
            {
                "satelliteId": 25545,
                "name": "STARLINK-STALE",
                "date": "2026-10-20T11:00:00Z",
                "line1": "1 25545U 98067A   21275.51005787  .00001490  00000-0  33219-4 0  9990",
                "line2": "2 25545  51.6442 209.3537 0003886  69.1842  47.1808 15.48815329305128",
            },
        ]
    }

    records = parse_alternate_tle_records([current], now)

    assert [sat.catalog_id for sat in records] == [25544]


def test_tracker_falls_back_when_celestrak_is_unavailable(monkeypatch):
    import app.tracking as tracking

    now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    alternate_items = []
    for norad_id in range(10000, 10120):
        alternate_items.append(
            {
                "satelliteId": norad_id,
                "name": f"STARLINK-{norad_id}",
                "date": now.isoformat(),
                "line1": (
                    f"1 25544U 98067A   21275.51005787  .00001490  "
                    f"00000-0  33219-4 0  9990"
                ),
                "line2": (
                    "2 25544  51.6442 209.3537 0003886  69.1842 "
                    "47.1808 15.48815329305128"
                ),
            }
        )

    def fake_read_json(url):
        if url == tracking.CELESTRAK_URL:
            raise tracking.URLError("403 Forbidden")
        return {"member": alternate_items}

    monkeypatch.setattr(tracking, "_read_json", fake_read_json)
    tracker = SatelliteTracker()

    assert tracker.refresh_if_due(now=now)
    status = tracker.status(now=now)
    assert status["available"]
    assert status["satellite_count"] == 120
    assert status["source"] == "TLE API Starlink search / SGP4 (CelesTrak fallback)"
    assert "CelesTrak unavailable" in status["error"]
