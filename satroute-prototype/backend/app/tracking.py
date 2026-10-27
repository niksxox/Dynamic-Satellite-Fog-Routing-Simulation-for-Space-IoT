"""Read-only satellite tracking from publicly published TLEs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import math
from threading import Lock
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
from sgp4.api import Satrec, jday

logger = logging.getLogger("satroute.tracking")

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=json"
ALTERNATE_TLE_URL = "https://tle.ivanstanojevic.me/api/tle/"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
TRACK_INTERVAL = timedelta(hours=2)
RETRY_INTERVAL = timedelta(minutes=10)
TRACKED_SATELLITE_COUNT = 120
ALTERNATE_MAX_PAGES = 12
MAX_TLE_AGE = timedelta(hours=48)
MAX_FUTURE_EPOCH = timedelta(hours=6)
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class TrackedSatellite:
    catalog_id: int
    name: str
    epoch: datetime
    record: Satrec


def parse_tle_records(
    payload: Any, *, limit: int | None = TRACKED_SATELLITE_COUNT
) -> list[TrackedSatellite]:
    """Parse CelesTrak GP JSON and retain valid named Starlink TLE records."""
    if not isinstance(payload, list):
        raise ValueError("CelesTrak response must be a JSON array")

    records: list[TrackedSatellite] = []
    seen_catalog_ids: set[int] = set()
    malformed_entries = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            catalog_id = int(item["NORAD_CAT_ID"])
            name = str(item.get("OBJECT_NAME") or item.get("TLE_LINE0") or f"STARLINK-{catalog_id}")
            line1 = str(item["TLE_LINE1"])
            line2 = str(item["TLE_LINE2"])
            epoch_text = str(item["EPOCH"]).replace("Z", "+00:00")
            epoch = datetime.fromisoformat(epoch_text)
            if epoch.tzinfo is None:
                epoch = epoch.replace(tzinfo=timezone.utc)
            record = Satrec.twoline2rv(line1, line2)
        except (KeyError, TypeError, ValueError):
            malformed_entries += 1
            continue

        if catalog_id in seen_catalog_ids:
            continue
        seen_catalog_ids.add(catalog_id)
        records.append(TrackedSatellite(catalog_id, name, epoch.astimezone(timezone.utc), record))

    if not records:
        raise ValueError("TLE response contained no valid satellite records")
    if malformed_entries:
        logger.warning("Skipped %d malformed TLE entries", malformed_entries)
    ordered = sorted(records, key=lambda sat: sat.catalog_id)
    return ordered[:limit] if limit is not None else ordered


def parse_alternate_tle_records(payloads: list[Any], now: datetime) -> list[TrackedSatellite]:
    """Parse recent Starlink records from the alternate paginated TLE API."""
    normalized_records: list[dict[str, Any]] = []
    current = now.astimezone(timezone.utc)
    for payload in payloads:
        if not isinstance(payload, dict) or not isinstance(payload.get("member"), list):
            raise ValueError("Alternate TLE response must contain a member array")
        for item in payload["member"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if "STARLINK" not in name.upper():
                continue
            try:
                epoch_text = str(item["date"]).replace("Z", "+00:00")
                epoch = datetime.fromisoformat(epoch_text)
                if epoch.tzinfo is None:
                    epoch = epoch.replace(tzinfo=timezone.utc)
                epoch = epoch.astimezone(timezone.utc)
                age = current - epoch
                if age > MAX_TLE_AGE or age < -MAX_FUTURE_EPOCH:
                    continue
                normalized_records.append(
                    {
                        "NORAD_CAT_ID": item["satelliteId"],
                        "OBJECT_NAME": name,
                        "EPOCH": epoch.isoformat(),
                        "TLE_LINE1": item["line1"],
                        "TLE_LINE2": item["line2"],
                    }
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Skipping malformed alternate TLE entry")

    if not normalized_records:
        return []
    normalized_records.sort(key=lambda item: item["EPOCH"], reverse=True)
    records = parse_tle_records(normalized_records, limit=None)
    records_by_id = {sat.catalog_id: sat for sat in records}
    recent_records = sorted(
        records_by_id.values(), key=lambda sat: sat.epoch, reverse=True
    )[:TRACKED_SATELLITE_COUNT]
    return sorted(recent_records, key=lambda sat: sat.catalog_id)


def _read_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": "SatRoute read-only orbital display",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload_bytes = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload_bytes) > MAX_RESPONSE_BYTES:
        raise ValueError("TLE provider response exceeded the 20 MB safety limit")
    return json.loads(payload_bytes)


def _julian_date(when: datetime) -> tuple[float, float]:
    utc = when.astimezone(timezone.utc)
    return jday(
        utc.year,
        utc.month,
        utc.day,
        utc.hour,
        utc.minute,
        utc.second + utc.microsecond / 1_000_000,
    )


def _teme_to_ecef(position_km: tuple[float, float, float], when: datetime) -> np.ndarray:
    jd, fraction = _julian_date(when)
    julian_centuries = ((jd + fraction) - 2451545.0) / 36525.0
    greenwich_sidereal_deg = (
        280.46061837
        + 360.98564736629 * ((jd + fraction) - 2451545.0)
        + 0.000387933 * julian_centuries**2
        - julian_centuries**3 / 38_710_000.0
    )
    angle = math.radians(greenwich_sidereal_deg % 360.0)
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y, z = position_km
    return np.array([cosine * x + sine * y, -sine * x + cosine * y, z], dtype=np.float64)


def propagate_positions(records: list[TrackedSatellite], when: datetime) -> np.ndarray:
    """Propagate TLEs with SGP4 and return Earth-fixed satellite positions in km."""
    jd, fraction = _julian_date(when)
    positions: list[np.ndarray] = []
    for satellite in records:
        error, position, _ = satellite.record.sgp4(jd, fraction)
        if error:
            raise RuntimeError(
                f"SGP4 could not propagate NORAD {satellite.catalog_id} "
                f"(error code {error})"
            )
        positions.append(_teme_to_ecef(position, when))
    return np.stack(positions)


def position_to_geodetic(position: np.ndarray) -> tuple[float, float, float]:
    """Convert Earth-fixed XYZ coordinates to spherical lat/lon and altitude."""
    x, y, z = (float(component) for component in position)
    radius = math.sqrt(x * x + y * y + z * z)
    latitude = math.degrees(math.atan2(z, math.hypot(x, y)))
    longitude = (math.degrees(math.atan2(y, x)) + 180.0) % 360.0 - 180.0
    return latitude, longitude, radius - EARTH_RADIUS_KM


class SatelliteTracker:
    """Thread-safe in-memory TLE cache with provider-friendly refresh intervals."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._refresh_lock = Lock()
        self._satellites: list[TrackedSatellite] = []
        self._refreshed_at: datetime | None = None
        self._next_refresh_at: datetime | None = None
        self._last_error: str | None = None
        self._source = "CelesTrak Starlink GP / SGP4"

    def refresh_if_due(self, now: datetime | None = None, force: bool = False) -> bool:
        current = now or datetime.now(timezone.utc)
        with self._refresh_lock:
            with self._lock:
                if not force and self._next_refresh_at and current < self._next_refresh_at:
                    return False

            primary_error: Exception | None = None
            try:
                records = parse_tle_records(_read_json(CELESTRAK_URL))
                if len(records) != TRACKED_SATELLITE_COUNT:
                    raise ValueError(
                        f"Expected at least {TRACKED_SATELLITE_COUNT} valid TLEs; "
                        f"received {len(records)}"
                    )
                propagate_positions(records, current)
            except (
                URLError,
                TimeoutError,
                OSError,
                ValueError,
                RuntimeError,
            ) as exc:
                primary_error = exc
                logger.warning("CelesTrak TLE refresh failed; trying alternate provider: %s", exc)
                try:
                    pages: list[Any] = []
                    records: list[TrackedSatellite] = []
                    for page in range(1, ALTERNATE_MAX_PAGES + 1):
                        pages.append(
                            _read_json(
                                f"{ALTERNATE_TLE_URL}?search=STARLINK&page={page}"
                            )
                        )
                        records = parse_alternate_tle_records(pages, current)
                        if len(records) >= TRACKED_SATELLITE_COUNT:
                            break
                    if len(records) < TRACKED_SATELLITE_COUNT:
                        raise ValueError(
                            f"Alternate TLE source returned only {len(records)} recent "
                            f"Starlink records; need {TRACKED_SATELLITE_COUNT}"
                        )
                    propagate_positions(records, current)
                except (
                    URLError,
                    TimeoutError,
                    OSError,
                    ValueError,
                    RuntimeError,
                ) as fallback_exc:
                    message = (
                        f"CelesTrak refresh failed: {primary_error}; "
                        f"alternate TLE refresh failed: {fallback_exc}"
                    )
                    logger.warning(message)
                    with self._lock:
                        self._last_error = message
                        self._next_refresh_at = current + RETRY_INTERVAL
                    return False

            with self._lock:
                self._satellites = records
                self._refreshed_at = current
                self._next_refresh_at = current + TRACK_INTERVAL
                if primary_error is None:
                    self._source = "CelesTrak Starlink GP / SGP4"
                    self._last_error = None
                else:
                    self._source = "TLE API Starlink search / SGP4 (CelesTrak fallback)"
                    self._last_error = (
                        f"CelesTrak unavailable ({primary_error}); using alternate TLE source"
                    )
            logger.info("Loaded %d Starlink TLE records from %s", len(records), self._source)
            return True

    def positions_ecef(self, when: datetime | None = None) -> np.ndarray | None:
        current = when or datetime.now(timezone.utc)
        with self._lock:
            records = list(self._satellites)
        if not records:
            return None
        try:
            return propagate_positions(records, current)
        except RuntimeError as exc:
            logger.error("Live orbital propagation failed: %s", exc)
            with self._lock:
                self._last_error = str(exc)
            return None

    def ground_track(self, satellite_index: int, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            if satellite_index < 0 or satellite_index >= len(self._satellites):
                raise ValueError("Satellite index is not present in the current TLE set")
            satellite = self._satellites[satellite_index]
            period_seconds = 2.0 * math.pi / satellite.record.no_kozai * 60.0
        count = min(181, max(2, math.ceil(period_seconds / 60.0) + 1))
        end = current + timedelta(seconds=period_seconds)
        points = []
        for index in range(count):
            sample_time = current + timedelta(seconds=period_seconds * index / (count - 1))
            position = propagate_positions([satellite], sample_time)[0]
            latitude, longitude, _ = position_to_geodetic(position)
            points.append([round(longitude, 4), round(latitude, 4)])
        return {
            "satellite_id": satellite_index,
            "norad_id": satellite.catalog_id,
            "name": satellite.name,
            "start": current.isoformat(),
            "end": end.isoformat(),
            "track": points,
        }

    def status(self, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            satellites = list(self._satellites)
            refreshed_at = self._refreshed_at
            last_error = self._last_error
            source = self._source
        oldest_epoch = min((sat.epoch for sat in satellites), default=None)
        age_seconds = (
            max(0.0, (current - oldest_epoch).total_seconds())
            if oldest_epoch
            else None
        )
        return {
            "available": bool(satellites),
            "source": source,
            "refreshed_at": refreshed_at.isoformat() if refreshed_at else None,
            "oldest_tle_epoch": oldest_epoch.isoformat() if oldest_epoch else None,
            "data_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "satellite_count": len(satellites),
            "satellites": [
                {"id": index, "norad_id": sat.catalog_id, "name": sat.name}
                for index, sat in enumerate(satellites)
            ],
            "error": last_error,
        }


satellite_tracker = SatelliteTracker()
