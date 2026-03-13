import asyncio
import json
import logging
import websockets
import motor.motor_asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve project root (parent of this file's folder)
BASE_DIR = Path(__file__).resolve().parent.parent  # backend/.. = website/
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


# MongoDB connection details
MONGO_URI = os.getenv("MONGO_URI")
WS_URL = 'wss://rpc.hyperliquid.xyz/ws'

# Logger setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("ExplorerTxTracker")

# Insert user if new (MongoDB does the uniqueness check)
async def add_user(users_collection, user):
    try:
        res = await users_collection.update_one(
            {"user": user},
            {"$setOnInsert": {"user": user}},
            upsert=True
        )
        if res.upserted_id:
            logger.info(f"\033[92mNew user saved to MongoDB: {user}\033[0m")
    except Exception as e:
        logger.error(f"Error inserting user {user}: {e}")

# Persistent websocket watcher
async def websocket_watcher():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client["hyperliquid"]
    users_collection = db["users"]

    while True:
        try:
            async with websockets.connect(WS_URL, origin="https://app.hyperliquid.xyz") as ws:
                logger.info("WebSocket connection opened")
                await ws.send(json.dumps({
                    "method": "subscribe",
                    "subscription": {"type": "explorerTxs"}
                }))
                async for message in ws:
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(data, list):
                        for tx in data:
                            user = tx.get("user") or tx.get("wallet")
                            if user:
                                await add_user(users_collection, user)
        except Exception as e:
            logger.error(f"WebSocket error: {e} - reconnecting in 5s...")
            await asyncio.sleep(5)

# Monitoring/analytics: records user count every day
async def daily_monitor():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client["hyperliquid"]
    users_collection = db["users"]
    monitor_collection = db["user_monitor"]

    while True:
        try:
            ts = datetime.now(timezone.utc).isoformat()
            user_count = await users_collection.count_documents({})
            doc = {"timestamp": ts, "user_count": user_count}
            await monitor_collection.insert_one(doc)
            logger.info(f"\033[94mMONITOR: Saved {user_count} users at {ts}\033[0m")
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        await asyncio.sleep(24 * 60 * 60)  # 24 hours

# Entry: run websocket watcher and monitor concurrently
async def main():
    await asyncio.gather(
        websocket_watcher(),
        daily_monitor()
    )

if __name__ == '__main__':
    asyncio.run(main())
