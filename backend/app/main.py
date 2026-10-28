import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="SatRoute API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text(json.dumps({"type": "hello", "msg": "satroute"}))
    n = 0
    try:
        while True:
            await asyncio.sleep(1.0)
            n += 1
            await websocket.send_text(json.dumps({"type": "tick", "n": n}))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
