import asyncio
import json
import logging
from pathlib import Path

import websockets

# Configuration
WS_URL = 'wss://rpc.hyperliquid.xyz/ws'
OUTPUT_FILE = Path('data/users.txt')

# Setup logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger('ExplorerTxTracker')

async def track_explorer_txs():
    seen = set()
    try:
        # Pass the Origin header correctly
        async with websockets.connect(WS_URL, origin="https://app.hyperliquid.xyz") as ws:
            logger.info("WebSocket connection opened")
            # Subscribe to the explorerTxs feed
            await ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {"type": "explorerTxs"}
            }))
            async for message in ws:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue

                # The explorerTxs feed sends an array of tx objects
                if isinstance(data, list):
                    for tx in data:
                        user = tx.get("user") or tx.get("wallet")
                        if user and user not in seen:
                            seen.add(user)
                            # Persist new user to disk
                            OUTPUT_FILE.write_text("\n".join(sorted(seen)) + "\n")
                            logger.info(f"New user: {user}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

    finally:
        logger.info("WebSocket closed, saving all seen users")
        OUTPUT_FILE.write_text("\n".join(sorted(seen)) + "\n")

if __name__ == '__main__':
    asyncio.run(track_explorer_txs())
