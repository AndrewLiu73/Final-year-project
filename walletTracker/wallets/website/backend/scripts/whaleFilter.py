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
from pathlib import Path
from dotenv import load_dotenv

# Resolve project root (parent of this file's folder)
BASE_DIR = Path(__file__).resolve().parent.parent  # backend/.. = website/
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("MillionaireUserFilter")

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "hyperliquid"
USERS_COLLECTION = "users"
MILLIONAIRE_COLLECTION = "millionaires"

CHECKPOINT_DIR = Path("../../../checkpoint")
CHECKPOINT_DIR.mkdir(exist_ok=True)
CHECKPOINT_FILE = CHECKPOINT_DIR / "millionaire_scan_checkpoint.txt"

MAX_REQUESTS_PER_MINUTE = 55
CONCURRENT_WORKERS = 10  # Process 10 wallets concurrently

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

def save_checkpoint(index: int, wallets_length: int):
    with open(CHECKPOINT_FILE, "w") as f:
        now = datetime.now(timezone.utc).isoformat()
        f.write(f"{index},{wallets_length},{now}\n")

def load_checkpoint():
    if not CHECKPOINT_FILE.exists():
        return 0
    with open(CHECKPOINT_FILE, "r") as f:
        line = f.readline().strip()
        if not line:
            return 0
        idx_s, wallets_s, *_ = line.split(",")
        return int(idx_s)

async def fetch_wallets_from_mongodb() -> list:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db[USERS_COLLECTION]
    cursor = users_collection.find({}, {"_id": 0, "user": 1})
    wallets = await cursor.to_list(length=None)
    client.close()
    return [doc["user"] for doc in wallets]

async def fetch_account_value_async(info: Info, wallet: str, rate_limiter: RateLimiter) -> tuple:
    await rate_limiter.acquire()
    try:
        loop = asyncio.get_event_loop()
        user_state = await loop.run_in_executor(None, info.user_state, wallet)
        if user_state and 'marginSummary' in user_state:
            account_value = float(user_state['marginSummary']['accountValue'])
            logger.info(f"{wallet} account value: ${account_value:,.2f}")
            return wallet, account_value
        else:
            logger.warning(f"Could not retrieve account value for {wallet}")
            return wallet, 0.0
    except Exception as e:
        logger.error(f"Error fetching account value for {wallet}: {e}")
        return wallet, 0.0

async def process_wallet_batch(
        wallets: List[str],
        info: Info,
        rate_limiter: RateLimiter,
        min_balance: float,
        millionaire_collection
) -> List[Dict]:
    tasks = [fetch_account_value_async(info, wallet, rate_limiter) for wallet in wallets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    millionaires = []
    bulk_operations = []

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Task failed with exception: {result}")
            continue

        wallet, balance = result
        if balance > min_balance:
            metrics = {'wallet': wallet, 'balance': balance}
            millionaires.append(metrics)
            logger.info(f"✅ {wallet} has account value ${balance:,.2f}")

            # Correct bulk update operation:
            bulk_operations.append(
                UpdateOne(
                    {"wallet": wallet},
                    {"$set": metrics},
                    upsert=True
                )
            )
        else:
            logger.info(f"❌ {wallet} balance below threshold")

    # Batch MongoDB updates
    if bulk_operations:
        try:
            await millionaire_collection.bulk_write(bulk_operations, ordered=False)
        except Exception as e:
            logger.error(f"Bulk write error: {e}")

    return millionaires

async def filter_millionaire_users(
        min_balance: float = 1_000_000,
        testnet: bool = False,
        batch_size: int = CONCURRENT_WORKERS
) -> list:
    wallets = await fetch_wallets_from_mongodb()
    logger.info(f"Loaded {len(wallets)} wallets from MongoDB")

    api_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
    info = Info(api_url, skip_ws=True)

    rate_limiter = RateLimiter(MAX_REQUESTS_PER_MINUTE)
    millionaires = []

    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    millionaire_collection = db[MILLIONAIRE_COLLECTION]

    last_idx = load_checkpoint()
    logger.info(f"Resuming from checkpoint index {last_idx}")

    remaining_wallets = wallets[last_idx:]

    try:
        # Process wallets in batches concurrently
        for batch_start in range(0, len(remaining_wallets), batch_size):
            batch = remaining_wallets[batch_start:batch_start + batch_size]
            current_idx = last_idx + batch_start

            logger.info(f"\n[{current_idx}/{len(wallets)}] Processing batch of {len(batch)} wallets")

            batch_millionaires = await process_wallet_batch(
                batch, info, rate_limiter, min_balance, millionaire_collection
            )
            millionaires.extend(batch_millionaires)
            save_checkpoint(current_idx + len(batch), len(wallets))
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        client.close()

    return millionaires

async def main():
    users = await filter_millionaire_users(
        min_balance=1_000_000,
        testnet=False,
        batch_size=CONCURRENT_WORKERS
    )
    if users:
        df = pd.DataFrame(users)
        output_csv = Path('../../../data/millionaire_users.csv')
        output_csv.parent.mkdir(exist_ok=True)
        df.to_csv(output_csv, index=False)
        logger.info(f"\n✅ Found {len(users)} users with >$1M account value")
        logger.info(f"Detailed metrics saved to {output_csv}")
    else:
        logger.info("\n❌ No users met the balance criteria")

if __name__ == '__main__':
    asyncio.run(main())
