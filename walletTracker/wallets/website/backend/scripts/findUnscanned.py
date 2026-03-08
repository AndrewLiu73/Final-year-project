"""
findUnscanned.py - shows which wallets in the users collection
don't have a matching document in profitability_metrics yet.

Basically the same $lookup the scanner uses in Phase 1, but
outputs the results so you can see exactly who's missing.
"""

import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

# load env from the backend directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MONGO_URI = os.getenv("MONGO_URI")


def find_unscanned():
    client = MongoClient(MONGO_URI)
    db = client["hyperliquid"]

    total_users = db.users.count_documents({"user": {"$exists": True}})
    total_metrics = db.profitability_metrics.count_documents({})

    print(f"Users collection:              {total_users:,}")
    print(f"Profitability metrics stored:   {total_metrics:,}")
    print(f"Expected unscanned:            ~{total_users - total_metrics:,}")
    print("-" * 55)

    # $lookup joins users → profitability_metrics on wallet address.
    # where the join produces an empty array = never scanned
    pipeline = [
        {"$match": {"user": {"$exists": True}}},
        {"$lookup": {
            "from": "profitability_metrics",
            "localField": "user",
            "foreignField": "wallet_address",
            "as": "metrics"
        }},
        {"$match": {"metrics": {"$size": 0}}},
        {"$project": {"user": 1, "_id": 0}},
    ]

    unscanned = list(db.users.aggregate(pipeline, allowDiskUse=True))
    print(f"Actual unscanned wallets:       {len(unscanned):,}\n")

    if not unscanned:
        print("All users have been scanned!")
        client.close()
        return

    # also check if any of these exist in profitability_metrics
    # under a slightly different address format (sanity check)
    print(f"First 50 unscanned wallets:")
    print("-" * 55)
    for i, doc in enumerate(unscanned[:50]):
        print(f"  {i+1:3d}. {doc['user']}")

    if len(unscanned) > 50:
        print(f"  ... and {len(unscanned) - 50:,} more")

    # optional: dump full list to a file
    if "--export" in sys.argv:
        out_path = os.path.join(os.path.dirname(__file__), "unscanned_wallets.txt")
        with open(out_path, "w") as f:
            for doc in unscanned:
                f.write(doc["user"] + "\n")
        print(f"\nFull list exported to: {out_path}")

    client.close()


if __name__ == "__main__":
    find_unscanned()

