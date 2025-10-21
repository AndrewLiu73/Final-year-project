import asyncio
import json
import logging
import websockets
import motor.motor_asyncio

# MongoDB connection details
MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
  # Change if using MongoDB Atlas
DB_NAME = "hyperliquid"
COLLECTION_NAME = "users"

# WebSocket URL
WS_URL = 'wss://rpc.hyperliquid.xyz/ws'

# Setup logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("ExplorerTxTracker")

async def track_explorer_txs():
    seen = set()
    # Create MongoDB client and collection
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db[COLLECTION_NAME]

    try:
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
                            # Insert user into MongoDB if not already present
                            await users_collection.update_one(
                                {"user": user},
                                {"$setOnInsert": {"user": user}},
                                upsert=True
                            )
                            logger.info(f"\033[92mNew user saved to MongoDB: {user}\033[0m")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        client.close()
        logger.info("MongoDB connection closed")

if __name__ == '__main__':
    asyncio.run(track_explorer_txs())
