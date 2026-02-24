import asyncio
import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

MONGO_URI                    = os.getenv("MONGO_URI")
DB_NAME                      = "hyperliquid"
PROFITABILITY_COLLECTION     = "profitability_metrics"
MILLIONAIRES_COLLECTION      = "millionaires"

# Minimum account value to qualify as a millionaire
THRESHOLD = 1_000_000.0


async def extract_millionaires():
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client[DB_NAME]

    profitability_coll = db[PROFITABILITY_COLLECTION]
    millionaires_coll  = db[MILLIONAIRES_COLLECTION]

    # Fetch all wallets above the threshold that have trading activity
    cursor = profitability_coll.find(
        {
            "account_value":        {"$gte": THRESHOLD},
            "has_trading_activity": True,
        },
        {
            "_id":           0,
            "wallet_address": 1,
            "account_value":  1,
        }
    )

    docs = await cursor.to_list(length=None)

    if not docs:
        print(f"No wallets found with account_value >= ${THRESHOLD:,.0f}")
        client.close()
        return

    print(f"Found {len(docs)} wallets with account_value >= ${THRESHOLD:,.0f}")

    inserted = 0
    updated  = 0
    skipped  = 0

    for doc in docs:
        wallet_address = doc.get("wallet_address")
        account_value  = doc.get("account_value", 0)

        if not wallet_address:
            skipped += 1
            continue

        # Upsert — if wallet already exists update balance, else insert
        result = await millionaires_coll.update_one(
            {"wallet": wallet_address},
            {
                "$set": {
                    "wallet":       wallet_address,
                    "balance":      account_value,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                },
                "$setOnInsert": {
                    "added_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True
        )

        if result.upserted_id:
            inserted += 1
        elif result.modified_count > 0:
            updated += 1
        else:
            skipped += 1

    print(f"Done — inserted: {inserted} | updated: {updated} | skipped: {skipped}")
    print(f"Total in millionaires collection: {await millionaires_coll.count_documents({})}")

    client.close()


async def remove_below_threshold():
    """
    Optional cleanup — removes wallets that have dropped below the threshold.
    Call this if you want the collection to stay current.
    """
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client[DB_NAME]

    profitability_coll = db[PROFITABILITY_COLLECTION]
    millionaires_coll  = db[MILLIONAIRES_COLLECTION]

    # Get all wallets currently in millionaires
    existing = await millionaires_coll.find({}, {"_id": 0, "wallet": 1}).to_list(None)
    existing_wallets = [d["wallet"] for d in existing if "wallet" in d]

    removed = 0
    for wallet in existing_wallets:
        # Check if they still qualify
        doc = await profitability_coll.find_one(
            {"wallet_address": wallet},
            {"account_value": 1}
        )
        if not doc or doc.get("account_value", 0) < THRESHOLD:
            await millionaires_coll.delete_one({"wallet": wallet})
            print(f"Removed {wallet} (balance dropped below threshold)")
            removed += 1

    print(f"Cleanup done — removed {removed} wallets below ${THRESHOLD:,.0f}")
    client.close()


async def main():
    print(f"Extracting millionaires from {PROFITABILITY_COLLECTION}...")
    print(f"Threshold: ${THRESHOLD:,.0f}")
    print("-" * 50)

    await extract_millionaires()

    # Uncomment the line below to also remove wallets that dropped below threshold
    # await remove_below_threshold()


if __name__ == "__main__":
    asyncio.run(main())
