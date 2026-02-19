"""
Remove duplicate wallet addresses from users collection
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def remove_duplicate_users():
    """Remove duplicate wallet addresses, keeping only one copy of each"""

    mongo_uri = os.getenv('MONGO_URI')

    if not mongo_uri:
        print("Error: MONGO_URI not found in .env file")
        return

    print("Connecting to MongoDB...")
    client = MongoClient(mongo_uri)
    db = client['hyperliquid']

    print("Analyzing users collection for duplicates...")

    # Find all duplicate wallet addresses
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
        print("\n✓ No duplicates found! Collection is clean.")
        return

    print(f"\nFound {len(duplicates)} wallet addresses with duplicates")

    total_to_delete = sum(len(dup['docs']) - 1 for dup in duplicates)
    print(f"Will remove {total_to_delete} duplicate documents")

    # Show some examples
    print("\nExample duplicates:")
    for i, dup in enumerate(duplicates[:5], 1):
        print(f"  {i}. Wallet: {dup['_id']} - {dup['count']} copies")

    if len(duplicates) > 5:
        print(f"  ... and {len(duplicates) - 5} more")

    # Confirm before deletion
    response = input(f"\nProceed with deletion? (yes/no): ")

    if response.lower() != 'yes':
        print("Cancelled. No changes made.")
        return

    print("\nRemoving duplicates...")
    deleted_count = 0

    for dup in duplicates:
        # Keep the first document, delete all others
        docs_to_delete = dup['docs'][1:]  # Skip first, delete rest
        result = db.users.delete_many({"_id": {"$in": docs_to_delete}})
        deleted_count += result.deleted_count

    print(f"\n✓ Successfully removed {deleted_count} duplicate documents")
    print(f"✓ Each wallet address now appears only once")

    # Verify
    remaining = db.users.count_documents({})
    print(f"\nFinal count: {remaining} unique users")


if __name__ == "__main__":
    print("=" * 60)
    print("MongoDB Duplicate Remover")
    print("=" * 60)
    print()
    remove_duplicate_users()
