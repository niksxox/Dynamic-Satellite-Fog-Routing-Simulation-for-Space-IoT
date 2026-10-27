"""Integration tests for FastAPI REST and WebSocket endpoints."""

import json
import pytest
from starlette.testclient import TestClient

from app.main import app, engine
from app.tracking import satellite_tracker


def test_tracking_status_endpoint_reports_read_only_source(monkeypatch):
    monkeypatch.setattr(satellite_tracker, "refresh_if_due", lambda: False)

    with TestClient(app) as client:
        response = client.get("/api/tracking")

    assert response.status_code == 200
    status = response.json()
    assert status["source"] == "CelesTrak Starlink GP / SGP4"
    assert isinstance(status["available"], bool)
    assert status["satellite_count"] == len(status["satellites"])


def test_1_health_and_state():
    """1. GET /health ok; GET /api/state returns a frame with 120 sats."""
    with TestClient(app) as client:
        # Health check
        res_health = client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json() == {"ok": True}

        # State snapshot
        res_state = client.get("/api/state")
        assert res_state.status_code == 200
        state = res_state.json()
        assert state["type"] == "frame"
        assert len(state["sats"]) == 120
        assert len(state["flows"]) == 8


def test_2_websocket_init_and_frames():
    """2. websocket_connect('/ws'): first message is type init with nSats 120;

    then at least 5 frames within 3 s; each frame has sats(120), links, flows(8), metrics.
    """
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            first_msg = ws.receive_json()
            assert first_msg["type"] == "init"
            assert first_msg["nSats"] == 120
            assert len(first_msg["ground"]) == 10
            assert len(first_msg["flows"]) == 8

            # Receive 5 frames
            for _ in range(5):
                frame = ws.receive_json()
                assert frame["type"] == "frame"
                assert len(frame["sats"]) == 120
                assert len(frame["flows"]) == 8
                assert len(frame["links"]) > 0
                assert "metrics" in frame
                assert "adaptive" in frame["metrics"]
                assert "static" in frame["metrics"]


def test_3_command_fail_link_and_event():
    """3. Send fail_link on a real link: receive an ack with id x1,

    and within a few frames an event with kind link_fail.
    """
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            init_msg = ws.receive_json()
            assert init_msg["type"] == "init"

            frame = ws.receive_json()
            assert frame["type"] == "frame"

            # Pick a real link from the frame
            target_link = frame["links"][0]
            u, v = target_link["a"], target_link["b"]

            # Send fail_link command
            cmd_msg = {
                "type": "cmd",
                "cmd": "fail_link",
                "args": {"a": u, "b": v},
                "id": "x1",
            }
            ws.send_text(json.dumps(cmd_msg))

            # Look for ack with id x1, then look for link_fail event in incoming frames
            found_ack = False
            found_event = False

            # Allow up to 15 messages to observe the ack and the event
            for _ in range(15):
                msg = ws.receive_json()
                if msg.get("type") == "ack" and msg.get("id") == "x1":
                    found_ack = True
                elif msg.get("type") == "frame":
                    events = msg.get("events", [])
                    if any(e.get("kind") == "link_fail" for e in events):
                        found_event = True
                if found_ack and found_event:
                    break

            assert found_ack, "Did not receive ack with id x1"
            assert found_event, "Did not receive frame with link_fail event"


def test_4_invalid_command_error_and_resilience():
    """4. Send an invalid command (unknown cmd, and bad args):

    receive an error message and frames keep arriving afterwards.
    """
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            init_msg = ws.receive_json()
            assert init_msg["type"] == "init"

            # Unknown command
            ws.send_text(json.dumps({"cmd": "non_existent_command", "id": "err1"}))
            err_msg1 = ws.receive_json()
            # If a frame slipped in before the error, read until we get the error
            while err_msg1.get("type") == "frame":
                err_msg1 = ws.receive_json()
            assert err_msg1["type"] == "error"
            assert "unknown command" in err_msg1["msg"].lower()

            # Bad args command
            ws.send_text(json.dumps({"cmd": "fail_link", "args": {"a": "invalid"}, "id": "err2"}))
            err_msg2 = ws.receive_json()
            while err_msg2.get("type") == "frame":
                err_msg2 = ws.receive_json()
            assert err_msg2["type"] == "error"
            assert "invalid arguments" in err_msg2["msg"].lower()

            # Verify frames keep arriving afterwards
            frame = ws.receive_json()
            while frame.get("type") != "frame":
                frame = ws.receive_json()
            assert frame["type"] == "frame"
            assert len(frame["sats"]) == 120


def test_5_multiple_clients():
    """5. Two clients connected at once both receive frames."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws1:
            with client.websocket_connect("/ws") as ws2:
                init1 = ws1.receive_json()
                init2 = ws2.receive_json()
                assert init1["type"] == "init"
                assert init2["type"] == "init"

                frame1 = ws1.receive_json()
                frame2 = ws2.receive_json()
                assert frame1["type"] == "frame"
                assert frame2["type"] == "frame"
                assert len(frame1["sats"]) == 120
                assert len(frame2["sats"]) == 120


def test_6_pause_play():
    """6. pause then t stops advancing in subsequent frames; play resumes."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # init

            # Get an initial frame
            f1 = ws.receive_json()
            while f1.get("type") != "frame":
                f1 = ws.receive_json()

            # Pause
            ws.send_text(json.dumps({"cmd": "pause", "id": "p1"}))
            # Wait for ack
            ack = ws.receive_json()
            while ack.get("type") != "ack":
                ack = ws.receive_json()

            # Collect subsequent frames while paused
            paused_times = []
            for _ in range(5):
                f = ws.receive_json()
                if f.get("type") == "frame":
                    paused_times.append(f["t"])

            assert len(paused_times) >= 3
            # Check all paused frames have the same timestamp
            assert all(t == paused_times[0] for t in paused_times), f"Time advanced while paused: {paused_times}"

            # Play
            ws.send_text(json.dumps({"cmd": "play", "id": "p2"}))
            ack2 = ws.receive_json()
            while ack2.get("type") != "ack":
                ack2 = ws.receive_json()

            # Wait for resumed frames
            resumed_times = []
            for _ in range(5):
                f = ws.receive_json()
                if f.get("type") == "frame":
                    resumed_times.append(f["t"])

            assert len(resumed_times) >= 3
            assert any(t > paused_times[0] for t in resumed_times), f"Time did not advance after play: {resumed_times}"
