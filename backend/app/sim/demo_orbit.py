"""Demonstration script for Walker Delta constellation orbit propagation."""

import numpy as np

from app.sim.constants import OMEGA_E
from app.sim.orbit import ecef_to_latlon, propagate_eci, positions_ecef, walker_delta


def main() -> None:
    # 1. Initialize Walker Delta constellation: 120 sats, 12 planes, F=1, inc=53 deg, alt=550 km
    constellation = walker_delta(
        num_sats=120,
        num_planes=12,
        f=1,
        inc_deg=53.0,
        altitude_km=550.0,
    )

    period = 2.0 * np.pi / constellation.n[0]

    # Speed from 1s finite difference in ECI
    r0 = propagate_eci(constellation, 0.0)[0]
    r1 = propagate_eci(constellation, 1.0)[0]
    speed = float(np.linalg.norm(r1 - r0))

    # Longitude drift after one orbital period in ECEF
    pos_ecef_t0 = positions_ecef(constellation, 0.0)[0]
    pos_ecef_tp = positions_ecef(constellation, period)[0]
    _, lon_t0, _ = ecef_to_latlon(pos_ecef_t0)
    _, lon_tp, _ = ecef_to_latlon(pos_ecef_tp)
    # Account for angle wrapping in [-180, 180]
    lon_drift = (lon_tp - lon_t0 + 180.0) % 360.0 - 180.0

    print("=" * 60)
    print("Walker Delta Constellation Simulation Demo (120/12/1, 53 deg, 550 km)")
    print("=" * 60)
    print(f"Orbital Period:                  {period:.2f} s")
    print(f"Orbital Speed (ECI 1s diff):     {speed:.4f} km/s")
    print(f"Longitude Drift (after 1 period): {lon_drift:.2f} deg")
    print("=" * 60)

    for t in [0.0, 600.0]:
        print(f"\n--- Positions at t = {t:.0f} s (first 5 satellites) ---")
        pos_ecef = positions_ecef(constellation, t)
        print(f"{'Sat':<5} | {'Plane':<6} | {'Latitude (deg)':<15} | {'Longitude (deg)':<15} | {'Altitude (km)':<15}")
        print("-" * 65)
        for i in range(5):
            lat, lon, alt = ecef_to_latlon(pos_ecef[i])
            plane = constellation.plane_index[i]
            print(f"{i:<5} | {plane:<6} | {lat:15.4f} | {lon:15.4f} | {alt:15.4f}")


if __name__ == "__main__":
    main()
