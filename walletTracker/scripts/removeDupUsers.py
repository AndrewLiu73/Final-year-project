"""
1. Remove extra fields from users collection (keep only _id and user)
2. Remove duplicate wallet addresses from users collection
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()


def cleanUsersCollection():

    mongoUri = os.getenv('MONGO_URI')

    if not mongoUri:
        print("Error: MONGO_URI not found in .env file")
        return

    print("Connecting to MongoDB...")
    client = MongoClient(mongoUri)

    db = client['hyperliquid']
    # run once in a script to backfill missing fields
    db.profitability_metrics.update_many(
        {"is_likely_bot": {"$exists": False}},
        {"$set": {"is_likely_bot": False}}
    )
    db.profitability_metrics.update_many(
        {"is_vault_depositor": {"$exists": False}},
        {"$set": {"is_vault_depositor": False}}
    )
    doc = db.profitability_metrics.find_one({"wallet_address": "0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00"})
    print(doc.get("is_likely_bot"))
    print(doc.get("is_vault_depositor"))

    # Step 1: Remove unwanted fields
    print("\nRemoving extra fields from users collection...")
    result = db.users.update_many(
        {},
        {
            "$unset": {
                "last_seen": "",
                "tx_count": "",
                "has_trading_activity": "",
                "is_profitable": "",
                "last_profitability_check": "",
                "total_pnl": "",
                "trade_count": "",
                "win_rate": ""
            }
        }
    )
    print(f"Fields removed - Matched: {result.matched_count}, Modified: {result.modified_count}")

    # Step 2: Remove duplicates
    print("\nAnalyzing users collection for duplicates...")

    pipeline = [
        {"$group": {
            "_id": "$user",
            "count": {"$sum": 1},
            "docs": {"$push": "$_id"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]

    duplicates = list(db.users.aggregate(pipeline))

    if not duplicates:
        print("No duplicates found. Collection is clean.")
        client.close()
        return

    print(f"Found {len(duplicates)} wallet addresses with duplicates")

    totalToDelete = sum(len(dup['docs']) - 1 for dup in duplicates)
    print(f"Will remove {totalToDelete} duplicate documents")

    print("\nExample duplicates:")
    for i, dup in enumerate(duplicates[:5], 1):
        print(f"  {i}. Wallet: {dup['_id']} - {dup['count']} copies")

    if len(duplicates) > 5:
        print(f"  ... and {len(duplicates) - 5} more")

    response = input("\nProceed with deletion? (yes/no): ")

    if response.lower() != 'yes':
        print("Cancelled. No changes made.")
        client.close()
        return

    print("\nRemoving duplicates...")
    deletedCount = 0

    for dup in duplicates:
        docsToDelete = dup['docs'][1:]
        result = db.users.delete_many({"_id": {"$in": docsToDelete}})
        deletedCount += result.deleted_count

    print(f"Successfully removed {deletedCount} duplicate documents")

    remaining = db.users.count_documents({})
    print(f"Final count: {remaining} unique users")

    client.close()


if __name__ == "__main__":
    print("=" * 60)
    print("MongoDB Users Collection Cleaner")
    print("=" * 60)
    print()
    cleanUsersCollection()
