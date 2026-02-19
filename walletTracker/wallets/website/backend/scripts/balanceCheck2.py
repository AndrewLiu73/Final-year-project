import asyncio
import logging
from pathlib import Path
import motor.motor_asyncio
import pandas as pd
from datetime import datetime, timezone
from pymongo import UpdateOne
from typing import List, Dict
import time

from hyperliquid.info import Info
from hyperliquid.utils import constants
import os
from dotenv import load_dotenv

# Resolve project root (parent of this file's folder)
BASE_DIR = Path(__file__).resolve().parent.parent  # backend/.. = website/
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("UserBalanceFetcher")

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "hyperliquid"
USERS_COLLECTION = "users"
BALANCES_COLLECTION = "balances"

# 🔹 checkpoint collection + key
CHECKPOINTS_COLLECTION = "checkpoints"
BALANCE_CHECKPOINT_ID = "balances_last_index"

MAX_REQUESTS_PER_MINUTE = 55
CONCURRENT_WORKERS = 10


class RateLimiter:
    def __init__(self, max_requests_per_minute: int):
        self.max_requests = max_requests_per_minute
        self.tokens = max_requests_per_minute
        self.updated_at = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            while self.tokens < 1:
                now = time.monotonic()
                time_passed = now - self.updated_at
                self.tokens += time_passed * (self.max_requests / 60.0)
                self.tokens = min(self.tokens, self.max_requests)
                self.updated_at = now
                if self.tokens < 1:
                    sleep_time = (1 - self.tokens) * (60.0 / self.max_requests)
                    await asyncio.sleep(sleep_time)
            self.tokens -= 1


# 🔹 checkpoint helpers
async def load_checkpoint() -> int:
    """Return last processed user index, or 0 if none."""
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    col = db[CHECKPOINTS_COLLECTION]
    try:
        doc = await col.find_one({"_id": BALANCE_CHECKPOINT_ID})
        return int(doc["last_index"]) if doc and "last_index" in doc else 0
    finally:
        client.close()


async def save_checkpoint(last_index: int) -> None:
    """Store last processed user index (inclusive)."""
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    col = db[CHECKPOINTS_COLLECTION]
    try:
        await col.update_one(
            {"_id": BALANCE_CHECKPOINT_ID},
            {
                "$set": {
                    "last_index": int(last_index),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        logger.info(f"📌 Checkpoint saved at user index {last_index}")
    finally:
        client.close()


# ✅ SINGLE fetch_users_from_mongodb
async def fetch_users_from_mongodb() -> List[Dict]:
    """Fetch ALL users from users collection (for full/iterative refresh)."""
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db[USERS_COLLECTION]
    try:
        cursor = users_collection.find({}, {"_id": 0, "user": 1})  # ALL users
        users = await cursor.to_list(length=None)
        logger.info(f"🔄 Loaded {len(users)} users for balance refresh")
        return users
    finally:
        client.close()


# ✅ fetch_account_balance_async
async def fetch_account_balance_async(info: Info, wallet: str, rate_limiter: RateLimiter) -> tuple:
    await rate_limiter.acquire()
    try:
        loop = asyncio.get_event_loop()
        user_state = await loop.run_in_executor(None, info.user_state, wallet)
        if user_state and 'marginSummary' in user_state:
            account_balance = float(user_state['marginSummary']['accountValue'])
            logger.info(f"✅ {wallet}: ${account_balance:,.2f}")
            return wallet, str(account_balance)
        else:
            logger.warning(f"⚠️ No balance data for {wallet}")
            return wallet, "0"
    except Exception as e:
        logger.error(f"❌ Error fetching {wallet}: {e}")
        return wallet, "0"


# ✅ process_user_batch
async def process_user_batch(
    users: List[Dict],
    info: Info,
    rate_limiter: RateLimiter,
    balances_collection,
) -> List[Dict]:
    wallets = [user["user"] for user in users]
    tasks = [fetch_account_balance_async(info, wallet, rate_limiter) for wallet in wallets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    bulk_operations = []
    success_count = 0
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Task failed: {result}")
            continue
        wallet, account_balance = result
        bulk_operations.append(
            UpdateOne({"user": wallet}, {"$set": {"account_balance": account_balance}}, upsert=True)
        )
        success_count += 1

    if bulk_operations:
        try:
            await balances_collection.bulk_write(bulk_operations, ordered=False)
            logger.info(f"💾 Updated {success_count} balances in batch")
        except Exception as e:
            logger.error(f"Bulk write error: {e}")
    return [result for result in results if not isinstance(result, Exception)]


async def fetch_all_user_balances(batch_size: int = CONCURRENT_WORKERS) -> List[Dict]:
    users = await fetch_users_from_mongodb()
    if not users:
        logger.info("✅ No users need balance fetching")
        return []

    total_users = len(users)
    logger.info(f"Starting balance fetch for {total_users} users")

    # 🔹 load checkpoint
    start_index = await load_checkpoint()
    if start_index >= total_users:
        logger.info("✅ Checkpoint beyond user list, resetting to 0")
        start_index = 0

    if start_index > 0:
        logger.info(f"⏩ Resuming from checkpoint at index {start_index}")

    api_url = constants.MAINNET_API_URL
    info = Info(api_url, skip_ws=True)
    rate_limiter = RateLimiter(MAX_REQUESTS_PER_MINUTE)

    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    balances_collection = db[BALANCES_COLLECTION]

    all_results = []
    try:
        for batch_start in range(start_index, total_users, batch_size):
            batch = users[batch_start:batch_start + batch_size]
            logger.info(f"\n[{batch_start}/{total_users}] Processing batch of {len(batch)} users")

            batch_results = await process_user_batch(batch, info, rate_limiter, balances_collection)
            all_results.extend(batch_results)

            # 🔹 save checkpoint after successful batch
            last_index = batch_start + len(batch) - 1
            await save_checkpoint(last_index)

            await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("⏹️ Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        client.close()

    logger.info(f"✅ Completed! Processed {len(all_results)} users")

    # Optional: reset checkpoint so next run always starts from 0
    # await save_checkpoint(0)

    return all_results


# ✅ create_balance_index
async def create_balance_index():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    balances_collection = db[BALANCES_COLLECTION]
    try:
        await balances_collection.create_index([("account_balance", 1)])
        logger.info("✅ Balance index created")
    finally:
        client.close()


# ✅ main
async def main():
    logger.info("🚀 Starting user balance fetcher")
    await create_balance_index()
    results = await fetch_all_user_balances()
    logger.info("🎉 Balance fetching complete!")


# ✅ periodic_runner
RUN_INTERVAL_SECONDS = 12 * 60 * 60  # 12 hours


async def periodic_runner():
    while True:
        try:
            await main()
        except Exception as e:
            logger.error(f"Run failed: {e}")
        logger.info("Sleeping 12 hours before next run...")
        await asyncio.sleep(RUN_INTERVAL_SECONDS)


if __name__ == '__main__':
    asyncio.run(periodic_runner())
