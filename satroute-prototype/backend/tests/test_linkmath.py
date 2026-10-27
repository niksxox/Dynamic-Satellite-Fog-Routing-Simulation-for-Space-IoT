"""Unit tests for link performance and queueing mathematics module."""

import numpy as np
import pytest

from app.sim.linkmath import (
    GSL_CAPACITY_MBPS,
    ISL_CAPACITY_MBPS,
    cong_loss,
    link_latency_ms,
    prop_ms,
    queue_ms,
    survive,
)


def test_1_prop_ms():
    """1. prop_ms(3600) ~= 12.008 (abs 0.01); prop_ms(0) == 0."""
    assert prop_ms(3600.0) == pytest.approx(12.008, abs=0.01)
    assert prop_ms(0.0) == 0.0


def test_2_queue_ms():
    """2. queue_ms(0)==0; queue_ms(0.5)==1.0; queue_ms(0.85)~=5.6667;

    queue_ms(0.97)~=32.333; queue_ms(1.2)==40.0; queue_ms reaches cap of 200 ms;
    queue_ms is non-decreasing over rho in 0..3.
    """
    assert queue_ms(0.0) == 0.0
    assert queue_ms(0.5) == pytest.approx(1.0)
    assert queue_ms(0.85) == pytest.approx(5.6667, abs=1e-3)
    assert queue_ms(0.97) == pytest.approx(32.333, abs=1e-3)
    assert queue_ms(1.2) == pytest.approx(40.0)

    # Under formula min(rho / (1 - min(rho, 0.97)), 200):
    # At rho=5.0: 5.0 / 0.03 = 166.67 ms. Cap of 200 ms is reached at rho >= 6.0.
    assert queue_ms(5.0) == pytest.approx(166.6667, abs=1e-3)
    assert queue_ms(6.0) == pytest.approx(200.0)
    assert queue_ms(10.0) == 200.0

    # queue_ms is non-decreasing over rho in 0..3
    rhos = np.linspace(0.0, 3.0, 100)
    delays = [queue_ms(r) for r in rhos]
    for i in range(len(delays) - 1):
        assert delays[i] <= delays[i + 1]


def test_3_cong_loss():
    """3. cong_loss(0.5)==0; cong_loss(0.85)==0; cong_loss(0.925)~=0.005; cong_loss(1.0)==0.02; cong_loss(2.0)==0.02."""
    assert cong_loss(0.5) == 0.0
    assert cong_loss(0.85) == 0.0
    assert cong_loss(0.925) == pytest.approx(0.005, abs=1e-4)
    assert cong_loss(1.0) == 0.02
    assert cong_loss(2.0) == 0.02


def test_4_survive():
    """4. survive(0)==0.999; survive(0.5)==0.999; survive(1.2)~=0.8159 (abs 0.001); survive(0.5, weather=0.15)~=0.999*0.85."""
    assert survive(0.0) == 0.999
    assert survive(0.5) == 0.999
    assert survive(1.2) == pytest.approx(0.8159, abs=0.001)
    assert survive(0.5, weather=0.15) == pytest.approx(0.999 * 0.85, abs=1e-6)


def test_5_link_latency_ms():
    """5. link_latency_ms(prop_ms(3600), 0.5) ~= 13.308 (abs 0.01)."""
    p = prop_ms(3600.0)
    assert link_latency_ms(p, 0.5) == pytest.approx(13.308, abs=0.01)


def test_6_array_input():
    """6. Array input: queue_ms(np.array([0,0.5,0.85])) returns an array of 3 values equal to the scalar results."""
    arr_in = np.array([0.0, 0.5, 0.85])
    arr_out = queue_ms(arr_in)

    assert isinstance(arr_out, np.ndarray)
    assert arr_out.shape == (3,)
    expected = np.array([queue_ms(0.0), queue_ms(0.5), queue_ms(0.85)])
    np.testing.assert_allclose(arr_out, expected, rtol=1e-7)

    # Also verify cong_loss, survive, prop_ms, link_latency_ms with arrays
    assert isinstance(cong_loss(arr_in), np.ndarray)
    assert isinstance(survive(arr_in), np.ndarray)
    assert isinstance(prop_ms(np.array([0.0, 3600.0])), np.ndarray)
    assert isinstance(link_latency_ms(prop_ms(arr_in), arr_in), np.ndarray)


def test_capacities():
    """Verify module capacity constants."""
    assert ISL_CAPACITY_MBPS == 2000.0
    assert GSL_CAPACITY_MBPS == 1000.0
