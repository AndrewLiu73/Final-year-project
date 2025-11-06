import asyncio
import json
import logging
import websockets
import motor.motor_asyncio

# MongoDB connection details
MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME = "hyperliquid"
USERS_COLLECTION = "users"
WS_URL = 'wss://rpc.hyperliquid.xyz/ws'

# Logger setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("ExplorerTxTracker")

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

async def websocket_watcher():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db[USERS_COLLECTION]

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

if __name__ == '__main__':
    asyncio.run(websocket_watcher())
