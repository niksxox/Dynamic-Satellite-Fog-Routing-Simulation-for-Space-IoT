"""Link performance and queueing mathematics for satellite networking.

Provides pure functions for propagation delay, M/M/1-approximated queueing delay,
congestion loss, link survival probability, and composite link latency.
Functions support both scalar and NumPy array inputs.
"""

from typing import Union

import numpy as np

from app.sim.constants import C_KMS, PROC_MS

ISL_CAPACITY_MBPS: float = 2000.0
GSL_CAPACITY_MBPS: float = 1000.0


def prop_ms(dist_km: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """Compute propagation delay in milliseconds given distance in kilometers.

    Args:
        dist_km: Distance in kilometers (scalar or ndarray).

    Returns:
        Propagation delay in milliseconds.
    """
    return dist_km / C_KMS * 1000.0


def queue_ms(rho: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """Compute queueing delay in milliseconds as a function of link utilization rho.

    Formula: min( 1.0 * rho / (1 - min(rho, 0.97)), 200 )

    Args:
        rho: Link traffic utilization (scalar or ndarray).

    Returns:
        Queueing delay in milliseconds capped at 200 ms.
    """
    r = np.asarray(rho, dtype=np.float64)
    denom = 1.0 - np.minimum(r, 0.97)
    val = np.minimum(1.0 * r / denom, 200.0)
    if isinstance(rho, (int, float, np.floating)):
        return float(val)
    return val


def cong_loss(rho: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """Compute congestion packet loss probability as a function of utilization rho.

    Formula: 0.02 * clip((rho - 0.85) / 0.15, 0, 1) ** 2

    Args:
        rho: Link traffic utilization (scalar or ndarray).

    Returns:
        Congestion packet loss probability in [0, 0.02].
    """
    r = np.asarray(rho, dtype=np.float64)
    norm = np.clip((r - 0.85) / 0.15, 0.0, 1.0)
    val = 0.02 * (norm**2)
    if isinstance(rho, (int, float, np.floating)):
        return float(val)
    return val


def survive(
    rho: Union[float, np.ndarray],
    base: float = 0.001,
    weather: float = 0.0,
) -> Union[float, np.ndarray]:
    """Compute link survival (packet delivery) probability.

    Formula: (1-base) * (1-cong_loss(rho)) * (1-weather) * min(1, 1/rho)
    Where rho <= 0 treats the last factor as 1.

    Args:
        rho: Link traffic utilization (scalar or ndarray).
        base: Baseline hardware / link loss probability (default 0.001).
        weather: Weather-induced impairment loss factor (default 0.0).

    Returns:
        Link survival probability.
    """
    r = np.asarray(rho, dtype=np.float64)
    safe_r = np.where(r > 0.0, r, 1.0)
    inv_r = 1.0 / safe_r
    last_factor = np.where(r <= 0.0, 1.0, np.minimum(1.0, inv_r))

    loss = cong_loss(r)
    val = (1.0 - base) * (1.0 - loss) * (1.0 - weather) * last_factor
    if isinstance(rho, (int, float, np.floating)):
        return float(val)
    return val


def link_latency_ms(
    prop: Union[float, np.ndarray],
    rho: Union[float, np.ndarray],
) -> Union[float, np.ndarray]:
    """Compute total one-way link latency in milliseconds.

    Formula: prop + PROC_MS + queue_ms(rho)

    Args:
        prop: Propagation delay in milliseconds (scalar or ndarray).
        rho: Link traffic utilization (scalar or ndarray).

    Returns:
        Total link latency in milliseconds.
    """
    q = queue_ms(rho)
    val = prop + PROC_MS + q
    if isinstance(prop, (int, float, np.floating)) and isinstance(
        rho, (int, float, np.floating)
    ):
        return float(val)
    return val
