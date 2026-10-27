"""FastAPI application for SatRoute simulation backend."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import copy
import logging
import time
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import orjson

from app.schemas import parse_command
from app.sim.engine import Engine
from app.sim.orbit import ground_track, rephase_to
from app.tracking import satellite_tracker

logger = logging.getLogger("satroute.main")
logging.basicConfig(level=logging.INFO)

# Global engine instance initialized with seed 42
engine: Engine = Engine(seed=42)


class ConnectionManager:
    """Manages active client WebSocket connections and broadcast dispatch."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()
        self.consecutive_failures: Dict[WebSocket, int] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        self.consecutive_failures[websocket] = 0

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        self.consecutive_failures.pop(websocket, None)

    async def broadcast_text(self, text: str) -> None:
        """Broadcast serialized frame text with per-client timeout guard."""
        if not self.active_connections:
            return

        dead_sockets: Set[WebSocket] = set()
        for ws in list(self.active_connections):
            try:
                # Per-client guard: skip/drop slow sends instead of queuing
                await asyncio.wait_for(ws.send_text(text), timeout=0.05)
                self.consecutive_failures[ws] = 0
            except (asyncio.TimeoutError, Exception) as exc:
                failures = self.consecutive_failures.get(ws, 0) + 1
                self.consecutive_failures[ws] = failures
                logger.debug("Broadcast send error/timeout to client (%d failures): %s", failures, exc)
                # Drop client after repeated failures or disconnects
                if failures >= 3 or isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                    dead_sockets.add(ws)

        for ws in dead_sockets:
            self.disconnect(ws)


manager = ConnectionManager()


async def simulation_loop() -> None:
    """Background simulation task running at 10 Hz with drift correction."""
    tick_interval = 0.1
    next_tick = time.perf_counter()

    while True:
        try:
            now = time.perf_counter()
            # If we fall more than 1 second behind, reset drift
            if now - next_tick > 1.0:
                next_tick = now

            next_tick += tick_interval
            delay = next_tick - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)

            # Advance simulation step (synchronous on same event loop thread)
            frame_data = engine.step(0.1)

            # Serialise frame ONCE with orjson and broadcast to all connected clients
            frame_bytes = orjson.dumps(frame_data)
            frame_text = frame_bytes.decode("utf-8")
            await manager.broadcast_text(frame_text)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("Unexpected error in simulation loop: %s", exc)
            await asyncio.sleep(0.01)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan managing background simulation loop task."""
    loop_task = asyncio.create_task(simulation_loop())
    yield
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="SatRoute Backend", lifespan=lifespan)

# CORS configuration for Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> Dict[str, bool]:
    """Health check endpoint."""
    return {"ok": True}


@app.get("/api/state")
async def get_state() -> Dict[str, Any]:
    """Return snapshot of engine simulation state."""
    return engine.snapshot()


@app.get("/api/tracking")
async def get_tracking_status() -> Dict[str, Any]:
    """Return read-only orbital data source, freshness, and tracked satellite IDs."""
    await asyncio.to_thread(satellite_tracker.refresh_if_due)
    if satellite_tracker.status()["available"]:
        engine.set_position_provider(satellite_tracker.positions_ecef)
    return satellite_tracker.status()


@app.get("/api/tracking/{satellite_index}/ground-track")
async def get_ground_track(satellite_index: int) -> Dict[str, Any]:
    """Return one predicted orbital ground track from the latest published TLE."""
    try:
        return satellite_tracker.ground_track(satellite_index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/reset")
async def reset_simulation() -> Dict[str, bool]:
    """Reset engine simulation state to initial conditions."""
    # Commands touching the engine cannot run concurrently with step():
    # both run on the same event loop thread and step() is synchronous, so this is safe.
    engine.apply_command("reset", {})
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Live WebSocket stream for constellation simulation frames and control commands."""
    await manager.connect(websocket)

    try:
        # Send initial static metadata frame
        init_data = engine.init_message()
        init_text = orjson.dumps(init_data).decode("utf-8")
        await websocket.send_text(init_text)

        # Loop receiving incoming JSON text commands
        while True:
            text = await websocket.receive_text()
            try:
                msg = orjson.loads(text)
            except Exception as exc:
                err_msg = {"type": "error", "msg": f"Invalid JSON payload: {exc}"}
                await websocket.send_text(orjson.dumps(err_msg).decode("utf-8"))
                continue

            req_id = msg.get("id")
            try:
                parsed_cmd = parse_command(msg)
                cmd_name = parsed_cmd.cmd
                args_dict = (
                    parsed_cmd.args.model_dump()
                    if hasattr(parsed_cmd.args, "model_dump")
                    else (parsed_cmd.args if isinstance(parsed_cmd.args, dict) else {})
                )

                # Special command: preview_orbit
                # reply {"type":"orbit_preview","id":id,"track":[[lon,lat],...]}
                # using a COPY of the constellation (never modify the real one)
                if cmd_name == "preview_orbit":
                    sat_id = int(args_dict.get("id", 0) if args_dict.get("id") is not None else 0)
                    lat = float(args_dict.get("lat", 0.0) if args_dict.get("lat") is not None else 0.0)
                    lon = float(args_dict.get("lon", 0.0) if args_dict.get("lon") is not None else 0.0)

                    c_copy = copy.deepcopy(engine.constellation)
                    rephase_to(c_copy, sat_id, lat, lon, engine.t)
                    # Compute 1 orbit ground track (e.g. 5400s / 90min, step 60s)
                    raw_track = ground_track(c_copy, sat_id, engine.t, engine.t + 5400.0, 60.0)
                    # Output [[lon, lat], ...]
                    track_coords = [[round(p_lon, 4), round(p_lat, 4)] for p_lat, p_lon in raw_track]

                    resp = {
                        "type": "orbit_preview",
                        "id": sat_id,
                        "track": track_coords,
                    }
                    await websocket.send_text(orjson.dumps(resp).decode("utf-8"))

                else:
                    # Commands touching the engine cannot run concurrently with step():
                    # both run on the same event loop thread and step() is synchronous, so this is safe.
                    engine.apply_command(cmd_name, args_dict)
                    ack_resp = {"type": "ack", "id": req_id}
                    await websocket.send_text(orjson.dumps(ack_resp).decode("utf-8"))

            except (ValueError, Exception) as exc:
                err_resp = {"type": "error", "msg": str(exc), "id": req_id}
                await websocket.send_text(orjson.dumps(err_resp).decode("utf-8"))

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception as exc:
        logger.debug("WebSocket handler exception: %s", exc)
    finally:
        manager.disconnect(websocket)
