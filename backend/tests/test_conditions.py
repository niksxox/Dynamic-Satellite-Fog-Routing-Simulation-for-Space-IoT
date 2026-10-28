"""Unit tests for conditions and dynamic failure model."""

import numpy as np
import pytest

from app.sim.conditions import (
    ConditionModel,
    FailParams,
    link_id_str,
    link_key,
    node_name,
)
from app.sim.linkmath import GSL_CAPACITY_MBPS, ISL_CAPACITY_MBPS
from app.sim.topology import GroundStation, Topology


def make_fake_topo(isl=None, gsl=None, n_sats=10, n_ground=2):
    isl_links = isl if isl is not None else [(0, 1), (1, 2), (3, 5)]
    gsl_links = gsl if gsl is not None else [(0, 10), (1, 11)]
    pos = np.zeros((n_sats, 3), dtype=np.float64)
    pos[:, 0] = np.arange(n_sats) * 1000.0
    ground_pos = np.zeros((n_ground, 3), dtype=np.float64)
    ground_pos[:, 1] = 6371.0
    dist = {
        (min(u, v), max(u, v)): 1000.0 for u, v in (isl_links + gsl_links)
    }
    return Topology(
        isl=isl_links,
        gsl=gsl_links,
        pos=pos,
        ground_pos=ground_pos,
        dist=dist,
    )


@pytest.fixture
def fake_ground():
    return [
        GroundStation(id=10, name="Delhi", lat=28.6, lon=77.2, ecef=np.array([6371.0, 0.0, 0.0])),
        GroundStation(id=11, name="London", lat=51.5, lon=-0.1, ecef=np.array([0.0, 6371.0, 0.0])),
    ]


def test_1_fail_link_and_recovery(fake_ground):
    """1. fail_link(3,5,t=0,duration=30): is_up false at t=29, true at t=31 after step()

    has run at t=31 (recovery event emitted); key order (5,3) behaves identically.
    """
    model = ConditionModel(np.random.default_rng(42), FailParams(), n_sats=10, ground=fake_ground)
    evt = model.fail_link(3, 5, t=0.0, duration=30.0)

    assert evt["level"] == "crit"
    assert evt["kind"] == "link_fail"
    assert evt["msg"] == "Link S003-S005 failed (manual)"

    assert not model.is_up(3, 5, t=29.0)
    assert not model.is_up(5, 3, t=29.0)

    topo = make_fake_topo(isl=[(3, 5)], gsl=[])
    events = model.step(topo, t=31.0, dt=1.0)

    # Recovery event emitted
    assert len(events) == 1
    assert events[0]["kind"] == "link_restore"
    assert events[0]["msg"] == "Link S003-S005 restored"
    assert events[0]["level"] == "info"

    assert model.is_up(3, 5, t=31.0)
    assert model.is_up(5, 3, t=31.0)


def test_2_persistence(fake_ground):
    """2. Persistence: link fails, drops out of topo for several steps (not in topo.isl), returns -> still down until its timer expires."""
    model = ConditionModel(np.random.default_rng(42), FailParams(), n_sats=10, ground=fake_ground)
    model.fail_link(3, 5, t=0.0, duration=100.0)
    assert not model.is_up(3, 5, t=10.0)

    # Simulate steps where (3, 5) is absent from the active topology
    empty_topo = make_fake_topo(isl=[(0, 1)], gsl=[])
    for t_step in [10.0, 20.0, 30.0, 40.0]:
        model.step(empty_topo, t=t_step, dt=10.0)

    # Link reappears in topology at t=50, must still be down
    topo_with_link = make_fake_topo(isl=[(3, 5)], gsl=[])
    assert not model.is_up(3, 5, t=50.0)
    assert model.failed_link_count(topo_with_link, t=50.0) == 1

    # After timer expires at t=105, recovers upon step
    events = model.step(topo_with_link, t=105.0, dt=5.0)
    assert any(e["kind"] == "link_restore" and "S003-S005" in e["msg"] for e in events)
    assert model.is_up(3, 5, t=105.0)
    assert model.failed_link_count(topo_with_link, t=105.0) == 0


def test_3_fail_node(fake_ground):
    """3. fail_node(4): every link touching node 4 reports down; restore_node fixes it."""
    model = ConditionModel(np.random.default_rng(42), FailParams(), n_sats=10, ground=fake_ground)
    evt = model.fail_node(4, t=0.0)
    assert evt["kind"] == "node_fail"
    assert evt["msg"] == "Node S004 failed"
    assert model.failed_node_count() == 1

    # Any link touching node 4 is down
    assert not model.is_up(4, 1, t=0.0)
    assert not model.is_up(2, 4, t=0.0)
    assert not model.is_up(4, 10, t=0.0)

    # Unrelated links remain up
    assert model.is_up(1, 2, t=0.0)

    # restore_node fixes it
    rest_evt = model.restore_node(4, t=10.0)
    assert rest_evt is not None
    assert rest_evt["kind"] == "node_restore"
    assert rest_evt["msg"] == "Node S004 restored"
    assert model.failed_node_count() == 0

    assert model.is_up(4, 1, t=10.0)
    assert model.is_up(2, 4, t=10.0)
    assert model.is_up(4, 10, t=10.0)


def test_4_manual_failure_infinite_duration(fake_ground):
    """4. Manual failure with duration None never auto-recovers over 1e6 s of steps; restore_link restores it."""
    model = ConditionModel(np.random.default_rng(42), FailParams(), n_sats=10, ground=fake_ground)
    model.fail_link(1, 2, t=0.0, duration=None)

    topo = make_fake_topo(isl=[(1, 2)], gsl=[])
    for t_val in np.linspace(100.0, 1e6, 20):
        events = model.step(topo, t=t_val, dt=50000.0)
        assert not model.is_up(1, 2, t=t_val)
        assert not any(e["kind"] == "link_restore" for e in events)

    # Manual restore
    rest_evt = model.restore_link(1, 2, t=1e6 + 5.0)
    assert rest_evt is not None
    assert rest_evt["kind"] == "link_restore"
    assert model.is_up(1, 2, t=1e6 + 5.0)


def test_5_determinism(fake_ground):
    """5. Determinism: two models with the same seed on the same topology over 500 steps produce identical event lists."""
    topo = make_fake_topo(isl=[(i, i + 1) for i in range(8)], gsl=[(0, 10), (1, 11)])
    params = FailParams(intensity=5.0)

    model1 = ConditionModel(np.random.default_rng(12345), params, n_sats=10, ground=fake_ground)
    model2 = ConditionModel(np.random.default_rng(12345), params, n_sats=10, ground=fake_ground)

    events1 = []
    events2 = []
    t = 0.0
    dt = 2.0
    for _ in range(500):
        t += dt
        e1 = model1.step(topo, t, dt)
        e2 = model2.step(topo, t, dt)
        events1.extend(e1)
        events2.extend(e2)

    assert len(events1) > 0, "Should have generated random failure/recovery events"
    assert events1 == events2


def test_6_random_failure_rate(fake_ground):
    """6. Random failure rate: with intensity=1000 and 100 links over 200 steps of dt=2 there are > 0 failures;

    with intensity=0 there are exactly 0.
    """
    links = [(i, i + 1) for i in range(100)]
    topo100 = make_fake_topo(isl=links, gsl=[], n_sats=102)

    # intensity = 1000 -> failures > 0
    model_high = ConditionModel(
        np.random.default_rng(42),
        FailParams(intensity=1000.0),
        n_sats=102,
        ground=fake_ground,
    )
    fails_high = 0
    t = 0.0
    for _ in range(200):
        t += 2.0
        evts = model_high.step(topo100, t, 2.0)
        fails_high += sum(1 for e in evts if e["kind"] == "link_fail")
    assert fails_high > 0

    # intensity = 0 -> exactly 0 failures
    model_zero = ConditionModel(
        np.random.default_rng(42),
        FailParams(intensity=0.0),
        n_sats=102,
        ground=fake_ground,
    )
    fails_zero = 0
    t = 0.0
    for _ in range(200):
        t += 2.0
        evts = model_zero.step(topo100, t, 2.0)
        fails_zero += sum(1 for e in evts if e["kind"] == "link_fail")
    assert fails_zero == 0


def test_7_risk(fake_ground):
    """7. risk: right after a failure risk ~0.6; after 60 s ~0.3; weather=0.15 gives risk 1.0 (clipped); healthy link risk 0."""
    model = ConditionModel(np.random.default_rng(42), FailParams(), n_sats=10, ground=fake_ground)

    # Healthy link: risk 0
    assert model.risk(1, 2, t=100.0) == 0.0

    # Right after failure: risk ~ 0.6
    model.fail_link(1, 2, t=100.0)
    assert model.risk(1, 2, t=100.0) == pytest.approx(0.6, abs=0.01)

    # After 60 s: risk ~ 0.3
    assert model.risk(1, 2, t=160.0) == pytest.approx(0.3, abs=0.01)

    # weather=0.15 gives risk 1.0 (clipped)
    assert model.risk(3, 4, t=100.0, weather=0.15) == pytest.approx(1.0)


def test_8_visible_down(fake_ground):
    """8. visible_down false at 0.5 s after failure, true at 1.0 s."""
    model = ConditionModel(
        np.random.default_rng(42),
        FailParams(detect_delay_s=1.0),
        n_sats=10,
        ground=fake_ground,
    )
    model.fail_link(2, 3, t=10.0)

    # 0.5 s after failure: not visible yet
    assert not model.visible_down(2, 3, t=10.5)

    # 1.0 s after failure: visible
    assert model.visible_down(2, 3, t=11.0)
    assert model.visible_down(2, 3, t=12.0)


def test_link_props_and_helpers(fake_ground):
    """Test link_props, helpers, and restore_all."""
    assert link_key(5, 3) == (3, 5)
    assert link_id_str(5, 3) == "3-5"
    assert node_name(3, 10, fake_ground) == "S003"
    assert node_name(10, 10, fake_ground) == "Delhi"

    topo = make_fake_topo(isl=[(0, 1)], gsl=[(0, 10)])
    model = ConditionModel(np.random.default_rng(42), FailParams(), n_sats=10, ground=fake_ground)

    props_isl = model.link_props(topo, 0, 1)
    assert props_isl["kind"] == 0
    assert props_isl["capacity_mbps"] == ISL_CAPACITY_MBPS
    assert props_isl["dist_km"] == 1000.0

    props_gsl = model.link_props(topo, 0, 10)
    assert props_gsl["kind"] == 1
    assert props_gsl["capacity_mbps"] == GSL_CAPACITY_MBPS

    model.fail_link(0, 1, t=0.0)
    model.fail_node(10, t=0.0)
    assert not model.is_up(0, 1, t=0.0)
    assert not model.is_up(0, 10, t=0.0)

    model.restore_all(t=1.0)
    assert model.is_up(0, 1, t=1.0)
    assert model.is_up(0, 10, t=1.0)
