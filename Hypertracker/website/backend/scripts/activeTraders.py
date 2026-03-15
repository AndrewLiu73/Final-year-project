import asyncio
import json
import websockets
import motor.motor_asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MONGO_URI = os.getenv("MONGO_URI")
WS_URL = 'wss://rpc.hyperliquid.xyz/ws'


async def main():
    db = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)["hyperliquid"]

    while True:
        async with websockets.connect(WS_URL, origin="https://app.hyperliquid.xyz") as ws:
            await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "explorerTxs"}}))
            async for message in ws:
                data = json.loads(message)
                if isinstance(data, list):
                    for tx in data:
                        user = tx.get("user") or tx.get("wallet")
                        if user:
                            await db["users"].update_one(
                                {"user": user},
                                {"$setOnInsert": {"user": user}},
                                upsert=True
                            )


if __name__ == '__main__':
    asyncio.run(main())
