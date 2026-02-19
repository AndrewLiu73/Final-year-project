import asyncio
import json
import logging
import websockets
import motor.motor_asyncio
from pymongo import UpdateOne
from datetime import datetime, timezone
import os
from pathlib import Path
from dotenv import load_dotenv
import aiohttp
import signal
from collections import deque
import time

# S3 dependencies (optional)
try:
    import boto3
    from botocore.client import Config as BotoConfig
    import lz4.frame
    import msgpack

    HAS_S3_SUPPORT = True
except ImportError:
    HAS_S3_SUPPORT = False
    logging.warning("S3 dependencies missing. Install: pip install boto3 lz4 msgpack")

# Load environment
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


# Configuration
class Config:
    MONGO_URI = os.getenv("MONGO_URI")
    DB_NAME = os.getenv("DB_NAME", "hyperliquid")
    USERS_COLLECTION = "users"
    MONITOR_COLLECTION = "user_monitor"
    METRICS_COLLECTION = "system_metrics"
    WS_URL = "wss://api.hyperliquid.xyz/ws"
    REST_API_URL = "https://api.hyperliquid.xyz/info"
    MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", 86400))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 500))
    BATCH_TIMEOUT = int(os.getenv("BATCH_TIMEOUT", 5))
    QUEUE_MAX_SIZE = int(os.getenv("QUEUE_MAX_SIZE", 10000))
    MAX_COIN_SUBSCRIPTIONS = int(os.getenv("MAX_COIN_SUBSCRIPTIONS", 50))

    # S3 settings - EDIT THESE TO CHANGE BLOCK RANGE
    USE_S3_BACKFILL = os.getenv("USE_S3_BACKFILL", "true").lower() == "true"
    S3_MAX_DOWNLOAD_GB = 100  # Stay within AWS Free Tier bandwidth
    S3_SKIP_FIRST_BLOCKS = 80000000  # Skip to Nov 2024 (~37M blocks ago)
    S3_MAX_BLOCKS_TO_PROCESS = 5_000_000  # Capture ~58 days (Nov-Dec 2024)

    @classmethod
    def validate(cls):
        if not cls.MONGO_URI:
            raise ValueError("MONGO_URI environment variable required")


Config.validate()

# Logger
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("HyperliquidTracker")

# Shutdown
shutdown_event = asyncio.Event()


def handle_shutdown(signum, frame):
    logger.info("Shutdown signal received")
    shutdown_event.set()


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# Rate Limiter
class RateLimiter:
    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()

    async def acquire(self):
        now = time.time()
        while self.calls and self.calls[0] < now - self.period:
            self.calls.popleft()

        if len(self.calls) >= self.max_calls:
            sleep_time = self.period - (now - self.calls[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            return await self.acquire()

        self.calls.append(now)


# Extract users
async def extract_all_users(data):
    """Extract all user addresses from any data structure"""
    users = set()

    user_fields = [
        'user', 'users', 'wallet', 'address', 'from', 'to',
        'sender', 'receiver', 'maker', 'taker', 'trader',
        'account', 'owner', 'liquidatedUser', 'liquidator'
    ]

    def extract_recursive(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in user_fields:
                    if isinstance(value, str) and value.startswith('0x') and len(value) == 42:
                        users.add(value.lower())
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, str) and item.startswith('0x') and len(item) == 42:
                                users.add(item.lower())
                else:
                    extract_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                extract_recursive(item)

    extract_recursive(data)
    return users


# Batch insert
async def batch_add_users(users_collection, user_batch):
    """Bulk insert users"""
    if not user_batch:
        return 0, 0

    try:
        current_time = datetime.now(timezone.utc).isoformat()

        operations = [
            UpdateOne(
                {"user": user},
                {
                    "$setOnInsert": {
                        "user": user,
                        "first_seen": current_time
                    },
                    "$set": {"last_seen": current_time},
                    "$inc": {"tx_count": 1}
                },
                upsert=True
            )
            for user in user_batch
        ]

        result = await users_collection.bulk_write(operations, ordered=False)
        new_users = result.upserted_count
        updated_users = result.modified_count

        if new_users > 0:
            logger.info(f"Batch: {new_users} new, {updated_users} updated")

        return new_users, updated_users

    except Exception as e:
        logger.error(f"Batch error: {e}")
        return 0, 0


# Log metrics
async def log_metrics(db, metric_type, value, metadata=None):
    metrics_collection = db[Config.METRICS_COLLECTION]
    doc = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metric_type": metric_type,
        "value": value,
        "metadata": metadata or {}
    }
    try:
        await metrics_collection.insert_one(doc)
    except Exception as e:
        logger.error(f"Error logging metrics: {e}")


# Setup indexes
async def setup_indexes(db):
    """Create database indexes (skip if already exist)"""
    try:
        users_collection = db[Config.USERS_COLLECTION]

        # Get existing indexes
        existing_indexes = await users_collection.index_information()

        # Only create if doesn't exist
        if 'user_1' not in existing_indexes:
            await users_collection.create_index("user", unique=True)
            logger.info("Created unique index on 'user'")
        else:
            logger.info("Index 'user_1' already exists, skipping")

        # Create other indexes
        if 'last_seen_-1' not in existing_indexes:
            await users_collection.create_index([("last_seen", -1)])

        if 'tx_count_-1' not in existing_indexes:
            await users_collection.create_index([("tx_count", -1)])

        if 'first_seen_-1' not in existing_indexes:
            await users_collection.create_index([("first_seen", -1)])

        logger.info("Database indexes verified")

    except Exception as e:
        logger.error(f"Index error: {e}")


# Get active coins
async def get_active_coins():
    """Get all active trading pairs"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    Config.REST_API_URL,
                    json={"type": "allMids"},
                    timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    mids = await resp.json()
                    return list(mids.keys())
    except Exception as e:
        logger.error(f"Error getting coins: {e}")

    return ["BTC", "ETH", "SOL", "ARB", "AVAX", "DOGE", "MATIC", "OP"]


# S3 backfill - Download specific block range (e.g., blocks 200k-400k)
async def backfill_from_s3_limited(users_collection):
    """
    S3 backfill - Download specific range of blocks
    Optimized for us-east-1 (Hyperliquid's bucket location)
    """
    if not HAS_S3_SUPPORT:
        logger.warning("S3 not available. Install: pip install boto3 lz4 msgpack")
        return 0

    SKIP_FIRST_N_BLOCKS = Config.S3_SKIP_FIRST_BLOCKS
    MAX_BLOCKS_TO_PROCESS = Config.S3_MAX_BLOCKS_TO_PROCESS

    logger.info("=" * 70)
    logger.info(f"S3 BACKFILL CONFIGURATION:")
    logger.info(f"  Skip first (most recent): {SKIP_FIRST_N_BLOCKS:,} blocks")
    logger.info(f"  Process next: {MAX_BLOCKS_TO_PROCESS:,} blocks")
    logger.info(
        f"  Target range: Block #{SKIP_FIRST_N_BLOCKS + 1:,} to #{SKIP_FIRST_N_BLOCKS + MAX_BLOCKS_TO_PROCESS:,}")
    logger.info(f"  Max download: {Config.S3_MAX_DOWNLOAD_GB} GB")
    logger.info("=" * 70)

    try:
        # Optimized S3 client configuration for us-east-1 (where Hyperliquid bucket is)
        s3_client = boto3.client(
            's3',
            region_name='us-east-1',  # Hyperliquid bucket is in us-east-1
            config=BotoConfig(
                signature_version='s3v4',
                s3={
                    'addressing_style': 'path'
                }
            )
        )

        bucket_name = "hl-mainnet-node-data"
        prefix = "explorer_blocks/"

        # List enough blocks to skip + process
        total_blocks_to_list = SKIP_FIRST_N_BLOCKS + MAX_BLOCKS_TO_PROCESS
        logger.info(f"Listing {total_blocks_to_list:,} blocks from S3...")
        logger.info(f"Bucket location: us-east-1 (US East - Virginia)")
        paginator = s3_client.get_paginator('list_objects_v2')

        all_blocks = []

        try:
            for page in paginator.paginate(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    RequestPayer='requester'
            ):
                if 'Contents' in page:
                    all_blocks.extend(page['Contents'])

                    if len(all_blocks) % 50000 == 0:
                        logger.info(f"Listed {len(all_blocks):,} blocks so far...")

                    # Stop listing after we have enough
                    if len(all_blocks) >= total_blocks_to_list:
                        logger.info(f"Reached {total_blocks_to_list:,} blocks, stopping listing")
                        break

        except Exception as e:
            logger.error(f"S3 listing error: {e}")
            logger.info("Possible issues:")
            logger.info("1. AWS credentials not configured: Run 'aws configure'")
            logger.info("2. No permission: Make sure IAM user has S3ReadOnlyAccess")
            logger.info("3. Check your AWS region configuration")
            return 0

        if not all_blocks:
            logger.warning("No blocks found in S3 bucket")
            return 0

        logger.info(f"Total blocks listed: {len(all_blocks):,}")

        # Sort by newest first
        logger.info("Sorting blocks by date (newest first)...")
        all_blocks.sort(key=lambda x: x['LastModified'], reverse=True)
        logger.info("Sorting complete")

        # Skip the first N blocks (most recent ones already captured)
        if SKIP_FIRST_N_BLOCKS > 0:
            logger.info(f"Skipping first {SKIP_FIRST_N_BLOCKS:,} blocks (already processed)...")
            blocks_to_consider = all_blocks[SKIP_FIRST_N_BLOCKS:]
            logger.info(f"Remaining blocks after skip: {len(blocks_to_consider):,}")
        else:
            blocks_to_consider = all_blocks

        # Calculate which blocks fit in 100GB limit
        logger.info(f"Calculating which blocks fit in {Config.S3_MAX_DOWNLOAD_GB} GB limit...")
        max_bytes = Config.S3_MAX_DOWNLOAD_GB * 1024 * 1024 * 1024
        cumulative_size = 0
        blocks_to_process = []

        for block in blocks_to_consider:
            if cumulative_size + block['Size'] > max_bytes:
                break
            blocks_to_process.append(block)
            cumulative_size += block['Size']

        total_size_gb = cumulative_size / (1024 ** 3)

        # Calculate block range info
        if blocks_to_process:
            first_block_date = blocks_to_process[0]['LastModified']
            last_block_date = blocks_to_process[-1]['LastModified']
        else:
            first_block_date = "N/A"
            last_block_date = "N/A"

        # Estimate costs
        request_cost = len(blocks_to_process) * 0.0004 / 1000  # $0.0004 per 1000 GET requests
        transfer_cost = total_size_gb * 0.09 if total_size_gb > 100 else 0  # First 100GB free
        total_estimated_cost = request_cost + transfer_cost

        logger.info("=" * 70)
        logger.info(f"S3 DOWNLOAD PLAN:")
        logger.info(f"  Total blocks listed: {len(all_blocks):,}")
        logger.info(f"  Skipped (recent): {SKIP_FIRST_N_BLOCKS:,}")
        logger.info(f"  Blocks to download: {len(blocks_to_process):,}")
        logger.info(
            f"  Actual range: Block #{SKIP_FIRST_N_BLOCKS + 1:,} to #{SKIP_FIRST_N_BLOCKS + len(blocks_to_process):,}")
        logger.info(f"  Size to download: {total_size_gb:.2f} GB")
        logger.info(f"  Date range: {last_block_date} to {first_block_date}")
        logger.info(f"  Estimated cost: ${total_estimated_cost:.3f}")
        logger.info(f"    - Request cost: ${request_cost:.3f}")
        logger.info(f"    - Transfer cost: ${transfer_cost:.3f} (first 100GB free)")
        logger.info("=" * 70)

        if len(blocks_to_process) == 0:
            logger.warning("No blocks to download after skipping and size calculation")
            return 0

        # Ask for confirmation
        logger.info(f"Ready to download {len(blocks_to_process):,} historical blocks")
        logger.info("Starting in 5 seconds... (Ctrl+C to cancel)")
        await asyncio.sleep(5)

        # Process blocks with progress updates
        logger.info("Starting block download and processing...")
        user_batch = set()
        total_new_users = 0
        downloaded_bytes = 0
        start_time = time.time()

        for i, block_obj in enumerate(blocks_to_process):
            if shutdown_event.is_set():
                logger.info("Shutdown requested, stopping...")
                break

            try:
                key = block_obj['Key']
                block_size_mb = block_obj['Size'] / (1024 * 1024)

                # Log every 10th block
                if i % 10 == 0:
                    actual_block_num = SKIP_FIRST_N_BLOCKS + i + 1
                    logger.info(f"[{i + 1}/{len(blocks_to_process)}] Processing block #{actual_block_num:,}")

                # Download
                response = s3_client.get_object(
                    Bucket=bucket_name,
                    Key=key,
                    RequestPayer='requester'
                )
                content = response['Body'].read()
                downloaded_bytes += len(content)

                # Decompress if needed
                if key.endswith('.lz4'):
                    content = lz4.frame.decompress(content)

                # Parse
                try:
                    if key.endswith('.rmp') or key.endswith('.rmp.lz4'):
                        block_data = msgpack.unpackb(content, raw=False)
                    else:
                        block_data = json.loads(content)
                except:
                    try:
                        block_data = json.loads(content)
                    except:
                        block_data = msgpack.unpackb(content, raw=False)

                # Extract users
                users = await extract_all_users(block_data)
                user_batch.update(users)

                # Batch insert every 50 blocks
                if len(user_batch) >= 500 or (i % 50 == 0 and user_batch):
                    new_count, _ = await batch_add_users(users_collection, user_batch)
                    total_new_users += new_count
                    user_batch.clear()

                    # Progress update every 50 blocks
                    if i % 50 == 0:
                        downloaded_gb = downloaded_bytes / (1024 ** 3)
                        progress_pct = (i + 1) / len(blocks_to_process) * 100
                        elapsed = time.time() - start_time
                        blocks_per_sec = (i + 1) / elapsed
                        eta_seconds = (len(blocks_to_process) - i - 1) / blocks_per_sec if blocks_per_sec > 0 else 0
                        eta_minutes = eta_seconds / 60

                        logger.info("=" * 70)
                        logger.info(f"PROGRESS UPDATE:")
                        logger.info(f"  Current position: Block #{SKIP_FIRST_N_BLOCKS + i + 1:,}")
                        logger.info(f"  Progress: {i + 1:,}/{len(blocks_to_process):,} ({progress_pct:.1f}%)")
                        logger.info(f"  Downloaded: {downloaded_gb:.2f}/{Config.S3_MAX_DOWNLOAD_GB} GB")
                        logger.info(f"  New users: {total_new_users:,}")
                        logger.info(f"  Speed: {blocks_per_sec:.2f} blocks/sec")
                        logger.info(f"  ETA: {eta_minutes:.1f} minutes")
                        logger.info("=" * 70)

            except Exception as e:
                logger.error(f"Error processing block {i + 1}: {e}")
                continue

        # Final batch
        if user_batch:
            logger.info(f"Saving final batch of {len(user_batch):,} users...")
            new_count, _ = await batch_add_users(users_collection, user_batch)
            total_new_users += new_count

        final_gb = downloaded_bytes / (1024 ** 3)
        total_time = time.time() - start_time
        actual_request_cost = len(blocks_to_process) * 0.0004 / 1000
        actual_transfer_cost = final_gb * 0.09 if final_gb > 100 else 0
        actual_total_cost = actual_request_cost + actual_transfer_cost

        logger.info("=" * 70)
        logger.info("S3 BACKFILL COMPLETE!")
        logger.info(f"  Block range: #{SKIP_FIRST_N_BLOCKS + 1:,} to #{SKIP_FIRST_N_BLOCKS + len(blocks_to_process):,}")
        logger.info(f"  Blocks processed: {len(blocks_to_process):,}")
        logger.info(f"  Downloaded: {final_gb:.2f} GB")
        logger.info(f"  New users: {total_new_users:,}")
        logger.info(f"  Time taken: {total_time / 60:.1f} minutes")
        logger.info(f"  Actual cost: ${actual_total_cost:.3f}")
        logger.info("=" * 70)

        return total_new_users

    except Exception as e:
        logger.error(f"S3 backfill failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0


# REST API backfill (FREE alternative)
async def backfill_from_rest_api(users_collection):
    """FREE: Use REST API (no AWS needed)"""
    logger.info("Starting FREE REST API backfill...")
    rate_limiter = RateLimiter(max_calls=30, period=60)

    coins = await get_active_coins()
    total_new_users = 0

    async with aiohttp.ClientSession() as session:
        for coin in coins[:30]:
            try:
                await rate_limiter.acquire()

                payload = {"type": "recentTrades", "coin": coin}

                async with session.post(
                        Config.REST_API_URL,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        trades = await resp.json()
                        user_batch = set()

                        for trade in trades:
                            users = await extract_all_users(trade)
                            user_batch.update(users)

                        if user_batch:
                            new_count, _ = await batch_add_users(users_collection, user_batch)
                            total_new_users += new_count
                            logger.info(f"{coin}: {new_count} new users")

            except Exception as e:
                logger.error(f"Error for {coin}: {e}")

    logger.info(f"REST backfill complete: {total_new_users} new users (FREE)")
    return total_new_users


# Real-time WebSocket
async def websocket_watcher(db):
    """Real-time trade tracking"""
    users_collection = db[Config.USERS_COLLECTION]

    coins = await get_active_coins()
    coins_to_monitor = coins[:Config.MAX_COIN_SUBSCRIPTIONS]

    logger.info(f"Monitoring {len(coins_to_monitor)} coins")

    message_queue = asyncio.Queue(maxsize=Config.QUEUE_MAX_SIZE)

    total_trades = 0
    total_new_users = 0
    start_time = datetime.now(timezone.utc)

    async def process_queue():
        user_batch = set()
        last_batch_time = datetime.now(timezone.utc)

        while not shutdown_event.is_set():
            try:
                try:
                    trade = await asyncio.wait_for(message_queue.get(), timeout=Config.BATCH_TIMEOUT)
                    users = await extract_all_users(trade)
                    user_batch.update(users)
                    message_queue.task_done()
                except asyncio.TimeoutError:
                    pass

                current_time = datetime.now(timezone.utc)
                time_elapsed = (current_time - last_batch_time).total_seconds()

                if len(user_batch) >= Config.BATCH_SIZE or (user_batch and time_elapsed >= Config.BATCH_TIMEOUT):
                    new_count, _ = await batch_add_users(users_collection, user_batch)
                    nonlocal total_new_users
                    total_new_users += new_count
                    user_batch.clear()
                    last_batch_time = current_time

            except Exception as e:
                logger.error(f"Queue error: {e}")
                await asyncio.sleep(1)

        if user_batch:
            await batch_add_users(users_collection, user_batch)

    processor_task = asyncio.create_task(process_queue())

    retry_delay = 5
    max_retry_delay = 300

    while not shutdown_event.is_set():
        try:
            async with websockets.connect(Config.WS_URL, ping_interval=20, ping_timeout=10) as ws:
                logger.info("WebSocket connected")
                retry_delay = 5

                for coin in coins_to_monitor:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "trades", "coin": coin}
                    }))
                    await asyncio.sleep(0.01)

                logger.info(f"Subscribed to {len(coins_to_monitor)} coins")

                async for message in ws:
                    if shutdown_event.is_set():
                        break

                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(data, dict) and data.get('channel') == 'subscriptionResponse':
                        continue

                    if isinstance(data, dict) and data.get('channel') == 'trades':
                        trade_list = data.get('data', [])
                        if not isinstance(trade_list, list):
                            trade_list = [trade_list]

                        for trade in trade_list:
                            try:
                                message_queue.put_nowait(trade)
                                total_trades += 1

                                if total_trades % 1000 == 0:
                                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                                    throughput = total_trades / elapsed if elapsed > 0 else 0
                                    logger.info(
                                        f"Stats: {total_trades} trades, {total_new_users} new users, {throughput:.2f}/s")

                            except asyncio.QueueFull:
                                logger.warning("Queue full")

        except Exception as e:
            logger.error(f"WebSocket error: {e} - reconnecting in {retry_delay}s")

        if not shutdown_event.is_set():
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)

    await processor_task


# Main
async def main():
    logger.info("=" * 70)
    logger.info("Hyperliquid User Tracker - Historical Backfill")
    logger.info("=" * 70)

    client = motor.motor_asyncio.AsyncIOMotorClient(Config.MONGO_URI)
    db = client[Config.DB_NAME]
    users_collection = db[Config.USERS_COLLECTION]

    await setup_indexes(db)

    # Historical backfill
    if Config.USE_S3_BACKFILL and HAS_S3_SUPPORT:
        await backfill_from_s3_limited(users_collection)
    else:
        await backfill_from_rest_api(users_collection)

    logger.info("Historical backfill complete. Shutting down...")
    client.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped")
