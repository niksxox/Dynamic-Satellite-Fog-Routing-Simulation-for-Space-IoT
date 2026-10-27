"""Link cost calculation for routing metrics."""

from __future__ import annotations

from typing import Sequence

DEFAULT_WEIGHTS: tuple[float, float, float] = (1.0, 1.0, 1.0)


def link_cost(
    lat_ms: float,
    rho: float,
    risk: float,
    w: Sequence[float] = DEFAULT_WEIGHTS,
) -> float:
    """Compute composite routing link cost.

    Formula:
        rho = min(rho, 0.99)
        cost = w[0]*(lat_ms/10.0) + w[1]*(0.25*rho/(1.0-rho)) + w[2]*(4.0*risk)

    Args:
        lat_ms: One-way link latency in milliseconds.
        rho: Link utilization fraction.
        risk: Dynamic routing failure risk in [0, 1].
        w: Component weights (latency, queueing/utilization, risk).

    Returns:
        Scalar link cost.
    """
    rho_clamped = min(float(rho), 0.99)
    term_lat = float(w[0]) * (float(lat_ms) / 10.0)
    term_rho = float(w[1]) * (0.25 * rho_clamped / (1.0 - rho_clamped))
    term_risk = float(w[2]) * (4.0 * float(risk))
    return term_lat + term_rho + term_risk
