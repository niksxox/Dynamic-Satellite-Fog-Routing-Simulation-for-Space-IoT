import { SatState } from '../net/types';
import { wrapLon } from '../lib/geo';

export interface InterpolatedSat {
  id: number;
  lat: number;
  lon: number;
  alt: number;
  st: 0 | 1 | 2 | 3;
}

/**
 * Extrapolates satellite positions at client render time `now` (performance.now()).
 * Follows docs/SPEC.md §13:
 * lat = f.lat + f.vlat * (now - recvAt) / 1000
 * lon = f.lon + f.vlon * (now - recvAt) / 1000 with wrap to [-180, 180]
 * Extrapolation is clamped to 300 ms to avoid drift on lag.
 */
export function satPositionsAt(
  sats: SatState[],
  recvAt: number,
  now: number
): InterpolatedSat[] {
  const dtMs = Math.max(0, Math.min(now - recvAt, 300));
  const dtSec = dtMs / 1000.0;

  return sats.map((sat) => {
    const lat = Math.max(-85, Math.min(85, sat.lat + sat.vlat * dtSec));
    const lon = wrapLon(sat.lon + sat.vlon * dtSec);

    return {
      id: sat.id,
      lat,
      lon,
      alt: sat.alt,
      st: sat.st,
    };
  });
}
