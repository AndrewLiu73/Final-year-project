import asyncio
import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

MONGO_URI = os.getenv("MONGO_URI")

# Minimum account value to qualify as a millionaire
THRESHOLD = 1_000_000.0


async def extractMillionaires():
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client["hyperliquid"]

    profitabilityColl = db["profitability_metrics"]
    millionairesColl  = db["millionaires"]

    # Fetch all wallets above the threshold that have trading activity
    cursor = profitabilityColl.find(
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
        walletAddress = doc.get("wallet_address")
        accountValue  = doc.get("account_value", 0)

        if not walletAddress:
            skipped += 1
            continue

        # Upsert — if wallet already exists update balance, else insert
        result = await millionairesColl.update_one(
            {"wallet": walletAddress},
            {
                "$set": {
                    "wallet":       walletAddress,
                    "balance":      accountValue,
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
    print(f"Total in millionaires collection: {await millionairesColl.count_documents({})}")

    client.close()


async def removeBelowThreshold():
    """
    Optional cleanup — removes wallets that have dropped below the threshold.
    Call this if you want the collection to stay current.
    """
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client["hyperliquid"]

    profitabilityColl = db["profitability_metrics"]
    millionairesColl  = db["millionaires"]

    # Get all wallets currently in millionaires
    existing = await millionairesColl.find({}, {"_id": 0, "wallet": 1}).to_list(None)
    existingWallets = [d["wallet"] for d in existing if "wallet" in d]

    removed = 0
    for wallet in existingWallets:
        # Check if they still qualify
        doc = await profitabilityColl.find_one(
            {"wallet_address": wallet},
            {"account_value": 1}
        )
        if not doc or doc.get("account_value", 0) < THRESHOLD:
            await millionairesColl.delete_one({"wallet": wallet})
            print(f"Removed {wallet} (balance dropped below threshold)")
            removed += 1

    print(f"Cleanup done — removed {removed} wallets below ${THRESHOLD:,.0f}")
    client.close()


async def main():
    print(f"Extracting millionaires from profitability_metrics...")
    print(f"Threshold: ${THRESHOLD:,.0f}")
    print("-" * 50)

    await extractMillionaires()

    # Uncomment the line below to also remove wallets that dropped below threshold
    # await removeBelowThreshold()


if __name__ == "__main__":
    asyncio.run(main())
