import asyncio
import json
import time
import websockets

async def probe():
    uri = "ws://localhost:8000/ws"
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as ws:
        # 1. Receive init
        raw_init = await ws.recv()
        init_data = json.loads(raw_init)
        print(f"✓ Received init: {init_data.get('type')}, sats: {init_data.get('nSats')}, ground: {len(init_data.get('ground', []))}")

        # 2. Receive 10 frames
        for i in range(10):
            t0 = time.perf_counter()
            msg = await ws.recv()
            dt = (time.perf_counter() - t0) * 1000
            data = json.loads(msg)
            t_sim = data.get("t")
            tick_ms = data.get("tickMs")
            sats_len = len(data.get("sats", []))
            links_len = len(data.get("links", []))
            flows_len = len(data.get("flows", []))
            size_kb = len(msg) / 1024
            print(f"Frame #{i+1}: t_sim={t_sim}s, sats={sats_len}, links={links_len}, flows={flows_len}, size={size_kb:.1f}KB, tickMs={tick_ms}ms (arrival: {dt:.1f}ms)")

        # 3. Test sending a command
        print("\nSending 'fail_link' command...")
        await ws.send(json.dumps({"type": "cmd", "cmd": "fail_link", "args": {"a": 0, "b": 1}, "id": "cmd-test-1"}))
        ack = await ws.recv()
        print(f"✓ Received reply: {ack}")

        # Check next frame for active failure & event
        msg = await ws.recv()
        data = json.loads(msg)
        print(f"✓ Post-command frame: activeFailures={data['metrics']['activeFailures']}, events={len(data['events'])}")

if __name__ == "__main__":
    asyncio.run(probe())
