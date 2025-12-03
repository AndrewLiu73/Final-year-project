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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("UserBalanceFetcher")

MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME = "hyperliquid"
USERS_COLLECTION = "users"
BALANCES_COLLECTION = "balances"

CHECKPOINT_DIR = Path("checkpoint")
CHECKPOINT_DIR.mkdir(exist_ok=True)
CHECKPOINT_FILE = CHECKPOINT_DIR / "balance_fetch_checkpoint.txt"

MAX_REQUESTS_PER_MINUTE = 55
CONCURRENT_WORKERS = 10


class RateLimiter:
    """Token bucket rate limiter for API requests"""

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


def save_checkpoint(index: int, total_users: int):
    with open(CHECKPOINT_FILE, "w") as f:
        now = datetime.now(timezone.utc).isoformat()
        f.write(f"{index},{total_users},{now}\n")


def load_checkpoint():
    if not CHECKPOINT_FILE.exists():
        return 0
    try:
        with open(CHECKPOINT_FILE, "r") as f:
            line = f.readline().strip()
            if not line:
                return 0
            idx_s, *_ = line.split(",")
            return int(idx_s)
    except:
        return 0


async def fetch_users_from_mongodb() -> List[Dict]:
    """Fetch all users from users collection"""
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db[USERS_COLLECTION]

    try:
        # Get users that don't have balance yet or need refresh
        cursor = users_collection.find(
            {"account_balance": {"$exists": False}},  # Only users without balance
            {"_id": 0, "user": 1}
        )
        users = await cursor.to_list(length=None)
        logger.info(f"Loaded {len(users)} users needing balance fetch")
        return users
    finally:
        client.close()


async def fetch_account_balance_async(info: Info, wallet: str, rate_limiter: RateLimiter) -> tuple:
    """Fetch account balance for single wallet"""
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


async def process_user_batch(
        users: List[Dict],
        info: Info,
        rate_limiter: RateLimiter,
        balances_collection
) -> List[Dict]:
    """Process a batch of users concurrently"""
    wallets = [user["user"] for user in users]
    tasks = [fetch_account_balance_async(info, wallet, rate_limiter) for wallet in wallets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    bulk_operations = []
    success_count = 0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Task failed: {result}")
            continue

        wallet, account_balance = result
        bulk_operations.append(
            UpdateOne(
                {"user": wallet},
                {"$set": {"account_balance": account_balance}},
                upsert=True
            )
        )
        success_count += 1

    # Update balances collection
    if bulk_operations:
        try:
            await balances_collection.bulk_write(bulk_operations, ordered=False)
            logger.info(f"💾 Updated {success_count} balances in batch")
        except Exception as e:
            logger.error(f"Bulk write error: {e}")

    return [result for result in results if not isinstance(result, Exception)]


async def fetch_all_user_balances(
        batch_size: int = CONCURRENT_WORKERS
) -> List[Dict]:
    """Main function to fetch balances for all users"""

    # Fetch users needing balances
    users = await fetch_users_from_mongodb()
    if not users:
        logger.info("✅ No users need balance fetching")
        return []

    total_users = len(users)
    logger.info(f"Starting balance fetch for {total_users} users")

    # Initialize API
    api_url = constants.MAINNET_API_URL
    info = Info(api_url, skip_ws=True)
    rate_limiter = RateLimiter(MAX_REQUESTS_PER_MINUTE)

    # MongoDB connection for balances
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    balances_collection = db[BALANCES_COLLECTION]

    last_idx = load_checkpoint()
    logger.info(f"Resuming from checkpoint index {last_idx}")

    remaining_users = users[last_idx:]
    all_results = []

    try:
        for batch_start in range(0, len(remaining_users), batch_size):
            batch = remaining_users[batch_start:batch_start + batch_size]
            current_idx = last_idx + batch_start

            logger.info(f"\n[{current_idx}/{total_users}] Processing batch of {len(batch)} users")

            batch_results = await process_user_batch(
                batch, info, rate_limiter, balances_collection
            )
            all_results.extend(batch_results)

            save_checkpoint(current_idx + len(batch), total_users)

            # Small delay between batches to be nice to API
            await asyncio.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("⏹️ Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        client.close()

    logger.info(f"✅ Completed! Processed {len(all_results)} users")
    return all_results


async def create_balance_index():
    """Create index on balances collection for fast queries"""
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    balances_collection = db[BALANCES_COLLECTION]

    try:
        await balances_collection.create_index([("account_balance", 1)])
        logger.info("✅ Balance index created")
    finally:
        client.close()


async def export_balances_to_csv():
    """Export all balances to CSV"""
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    balances_collection = db[BALANCES_COLLECTION]

    try:
        cursor = balances_collection.find({}, {"_id": 0, "user": 1, "account_balance": 1})
        balances = await cursor.to_list(length=None)

        if balances:
            df = pd.DataFrame(balances)
            output_path = Path("data/all_balances.csv")
            output_path.parent.mkdir(exist_ok=True)
            df.to_csv(output_path, index=False)
            logger.info(f"📊 Exported {len(balances)} balances to {output_path}")
    finally:
        client.close()


async def main():
    """Main entry point"""
    logger.info("🚀 Starting user balance fetcher")

    # Create index for fast queries
    await create_balance_index()

    # Fetch balances for users without them
    results = await fetch_all_user_balances()


    logger.info("🎉 Balance fetching complete!")

RUN_INTERVAL_SECONDS = 12 * 60 * 60  # 12 hours

async def periodic_runner():
    while True:
        try:
            await main()  # run your existing pipeline once
        except Exception as e:
            logger.error(f"Run failed: {e}")
        logger.info("Sleeping 12 hours before next run...")
        await asyncio.sleep(RUN_INTERVAL_SECONDS)

if __name__ == '__main__':
    asyncio.run(periodic_runner())

