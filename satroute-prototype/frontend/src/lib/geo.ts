/**
 * Geographic utility functions for map rendering and antimeridian handling.
 */

export interface Point2D {
  lon: number;
  lat: number;
}

/**
 * Shortest arc longitude wrap between [-180, 180].
 */
export function wrapLon(lon: number): number {
  return ((lon + 180) % 360 + 360) % 360 - 180;
}

/**
 * Split a segment between p1 and p2 at the antimeridian (+/-180) if it crosses it,
 * preventing lines from drawing all the way across the globe in 2D projected maps.
 */
export function splitAntimeridianSegment(
  p1: [number, number],
  p2: [number, number]
): [number, number][][] {
  const [lon1, lat1] = p1;
  const [lon2, lat2] = p2;

  const dLon = lon2 - lon1;

  // If the segment crosses the antimeridian (|dLon| > 180)
  if (Math.abs(dLon) > 180) {
    let sign = dLon > 0 ? -1 : 1;
    let crossLon1 = sign > 0 ? 180 : -180;
    let crossLon2 = sign > 0 ? -180 : 180;

    // Fraction of longitude distance
    const totalDist = 360 - Math.abs(dLon);
    const distToBorder1 = sign > 0 ? 180 - lon1 : lon1 + 180;
    const frac = Math.max(0, Math.min(1, distToBorder1 / totalDist));
    const crossLat = lat1 + (lat2 - lat1) * frac;

    return [
      [
        [lon1, lat1],
        [crossLon1, crossLat],
      ],
      [
        [crossLon2, crossLat],
        [lon2, lat2],
      ],
    ];
  }

  return [[[lon1, lat1], [lon2, lat2]]];
}
