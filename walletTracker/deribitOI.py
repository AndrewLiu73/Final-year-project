import asyncio
import websockets
import json
import ssl
import certifi
from datetime import datetime, timezone

# Globals
DERIBIT_WS_URL = "wss://www.deribit.com/ws/api/v2"
INSTRUMENT     = "BTC-PERPETUAL"
INTERVAL       = "100ms"  # still ~10 updates/sec
deribit_oi     = None     # holds the latest open_interest

async def deribit_ws_listener():
    """
    Subscribes to Deribit’s ticker feed and updates the global deribit_oi.
    """
    global deribit_oi
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    async with websockets.connect(DERIBIT_WS_URL, ssl=ssl_ctx) as ws:
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "method": "public/subscribe",
            "id": 1,
            "params": {
                "channels": [f"ticker.{INSTRUMENT}.{INTERVAL}"]
            }
        }))
        async for msg in ws:
            data = json.loads(msg).get("params", {}).get("data", {})
            if "open_interest" in data:
                deribit_oi = float(data["open_interest"])

async def print_minute_oi():
    """
    Prints the latest deribit_oi once every 60 seconds.
    """
    global deribit_oi
    # allow first WS message to arrive
    await asyncio.sleep(1)
    while True:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if deribit_oi is not None:
            print(f"[{ts}] Deribit open_interest: {deribit_oi:,}")
        else:
            print(f"[{ts}] Deribit open_interest: None")
        await asyncio.sleep(60)

async def main():
    await asyncio.gather(
        deribit_ws_listener(),
        print_minute_oi()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
