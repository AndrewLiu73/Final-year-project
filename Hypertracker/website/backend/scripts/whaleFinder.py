import asyncio
import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MONGO_URI  = os.getenv("MONGO_URI")
min  = 1000000.0


def db():
    return AsyncIOMotorClient(MONGO_URI)["hyperliquid"]

async def extract_millionaires():
    d    = db()
    now  = datetime.now(timezone.utc).isoformat()
    docs = await d["profitability_metrics"].find(
        {"account_value": {"$gte": min}, "has_trading_activity": True},
        {"_id": 0, "wallet_address": 1, "account_value": 1}
    ).to_list(None)

    for doc in docs:
        if wallet := doc.get("wallet_address"):
            await d["millionaires"].update_one(
                {"wallet": wallet},
                {"$set": {"wallet": wallet, "balance": doc["account_value"], "last_updated": now},
                 "$setOnInsert": {"added_at": now}},
                upsert=True
            )
    print(f"Processed {len(docs)} wallets")

if __name__ == "__main__":
    asyncio.run(extract_millionaires())
