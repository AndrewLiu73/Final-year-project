import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
# from motor.motor_asyncio import AsyncIOMotorClient

from sqlite_db import get_async_connection, loads

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# MONGO_URI = os.getenv("MONGO_URI")
min  = 1000000.0


# def db():
#     return AsyncIOMotorClient(MONGO_URI)["hyperliquid"]

async def extract_millionaires():
    # d = db()
    conn = await get_async_connection()
    now  = datetime.now(timezone.utc).isoformat()
    # docs = await d["profitability_metrics"].find(
    #     {"account_value": {"$gte": min}, "has_trading_activity": True},
    #     {"_id": 0, "wallet_address": 1, "account_value": 1}
    # ).to_list(None)
    cursor = await conn.execute(
        "SELECT wallet_address, account_value FROM profitability_metrics "
        "WHERE account_value >= ? AND has_trading_activity = 1",
        (min,),
    )
    docs = await cursor.fetchall()

    for doc in docs:
        if wallet := doc["wallet_address"]:
            # await d["millionaires"].update_one(
            #     {"wallet": wallet},
            #     {"$set": {"wallet": wallet, "balance": doc["account_value"], "last_updated": now},
            #      "$setOnInsert": {"added_at": now}},
            #     upsert=True
            # )
            existing_cursor = await conn.execute("SELECT data FROM millionaires WHERE wallet = ?", (wallet,))
            existing_row = await existing_cursor.fetchone()
            added_at = loads(existing_row["data"]).get("added_at", now) if existing_row else now
            balance = doc["account_value"]
            data = {"wallet": wallet, "balance": balance, "last_updated": now, "added_at": added_at}
            await conn.execute(
                "INSERT INTO millionaires (wallet, balance, last_updated, data) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(wallet) DO UPDATE SET balance=excluded.balance, "
                "last_updated=excluded.last_updated, data=excluded.data",
                (wallet, balance, now, json.dumps(data)),
            )
    await conn.commit()
    await conn.close()
    print(f"Processed {len(docs)} wallets")

if __name__ == "__main__":
    asyncio.run(extract_millionaires())
