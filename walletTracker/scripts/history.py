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


def handleShutdown(signum, frame):
    logger.info("Shutdown signal received")
    shutdown_event.set()


signal.signal(signal.SIGINT, handleShutdown)
signal.signal(signal.SIGTERM, handleShutdown)


# Rate Limiter
class RateLimiter:
    def __init__(self, maxCalls, period):
        self.maxCalls = maxCalls
        self.period = period
        self.calls = deque()

    async def acquire(self):
        now = time.time()
        while self.calls and self.calls[0] < now - self.period:
            self.calls.popleft()

        if len(self.calls) >= self.maxCalls:
            sleepTime = self.period - (now - self.calls[0])
            if sleepTime > 0:
                await asyncio.sleep(sleepTime)
            return await self.acquire()

        self.calls.append(now)


# Extract users
async def extractAllUsers(data):
    """Extract all user addresses from any data structure"""
    users = set()

    user_fields = [
        'user', 'users', 'wallet', 'address', 'from', 'to',
        'sender', 'receiver', 'maker', 'taker', 'trader',
        'account', 'owner', 'liquidatedUser', 'liquidator'
    ]

    def extractRecursive(obj):
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
                    extractRecursive(value)
        elif isinstance(obj, list):
            for item in obj:
                extractRecursive(item)

    extractRecursive(data)
    return users


# Batch insert
async def batchAddUsers(usersCollection, userBatch):
    """Bulk insert users"""
    if not userBatch:
        return 0, 0

    try:
        currentTime = datetime.now(timezone.utc).isoformat()

        operations = [
            UpdateOne(
                {"user": user},
                {
                    "$setOnInsert": {
                        "user": user,
                        "first_seen": currentTime
                    },
                    "$set": {"last_seen": currentTime},
                    "$inc": {"tx_count": 1}
                },
                upsert=True
            )
            for user in userBatch
        ]

        result = await usersCollection.bulk_write(operations, ordered=False)
        newUsers = result.upserted_count
        updatedUsers = result.modified_count

        if newUsers > 0:
            logger.info(f"Batch: {newUsers} new, {updatedUsers} updated")

        return newUsers, updatedUsers

    except Exception as e:
        logger.error(f"Batch error: {e}")
        return 0, 0


# Log metrics
async def logMetrics(db, metricType, value, metadata=None):
    metrics_collection = db["system_metrics"]
    doc = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metric_type": metricType,
        "value": value,
        "metadata": metadata or {}
    }
    try:
        await metrics_collection.insert_one(doc)
    except Exception as e:
        logger.error(f"Error logging metrics: {e}")


# Setup indexes
async def setupIndexes(db):
    """Create database indexes (skip if already exist)"""
    try:
        usersCollection = db["users"]

        # Get existing indexes
        existingIndexes = await usersCollection.index_information()

        # Only create if doesn't exist
        if 'user_1' not in existingIndexes:
            await usersCollection.create_index("user", unique=True)
            logger.info("Created unique index on 'user'")
        else:
            logger.info("Index 'user_1' already exists, skipping")

        # Create other indexes
        if 'last_seen_-1' not in existingIndexes:
            await usersCollection.create_index([("last_seen", -1)])

        if 'tx_count_-1' not in existingIndexes:
            await usersCollection.create_index([("tx_count", -1)])

        if 'first_seen_-1' not in existingIndexes:
            await usersCollection.create_index([("first_seen", -1)])

        logger.info("Database indexes verified")

    except Exception as e:
        logger.error(f"Index error: {e}")


# Get active coins
async def getActiveCoins():
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
async def backfillFromS3Limited(usersCollection):
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

        allBlocks = []

        try:
            for page in paginator.paginate(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    RequestPayer='requester'
            ):
                if 'Contents' in page:
                    allBlocks.extend(page['Contents'])

                    if len(allBlocks) % 50000 == 0:
                        logger.info(f"Listed {len(allBlocks):,} blocks so far...")

                    # Stop listing after we have enough
                    if len(allBlocks) >= total_blocks_to_list:
                        logger.info(f"Reached {total_blocks_to_list:,} blocks, stopping listing")
                        break

        except Exception as e:
            logger.error(f"S3 listing error: {e}")
            logger.info("Possible issues:")
            logger.info("1. AWS credentials not configured: Run 'aws configure'")
            logger.info("2. No permission: Make sure IAM user has S3ReadOnlyAccess")
            logger.info("3. Check your AWS region configuration")
            return 0

        if not allBlocks:
            logger.warning("No blocks found in S3 bucket")
            return 0

        logger.info(f"Total blocks listed: {len(allBlocks):,}")

        # Sort by newest first
        logger.info("Sorting blocks by date (newest first)...")
        allBlocks.sort(key=lambda x: x['LastModified'], reverse=True)
        logger.info("Sorting complete")

        # Skip the first N blocks (most recent ones already captured)
        if SKIP_FIRST_N_BLOCKS > 0:
            logger.info(f"Skipping first {SKIP_FIRST_N_BLOCKS:,} blocks (already processed)...")
            blocksToConsider = allBlocks[SKIP_FIRST_N_BLOCKS:]
            logger.info(f"Remaining blocks after skip: {len(blocksToConsider):,}")
        else:
            blocksToConsider = allBlocks

        # Calculate which blocks fit in 100GB limit
        logger.info(f"Calculating which blocks fit in {Config.S3_MAX_DOWNLOAD_GB} GB limit...")
        maxBytes = Config.S3_MAX_DOWNLOAD_GB * 1024 * 1024 * 1024
        cumulativeSize = 0
        blocksToProcess = []

        for block in blocksToConsider:
            if cumulativeSize + block['Size'] > maxBytes:
                break
            blocksToProcess.append(block)
            cumulativeSize += block['Size']

        totalSizeGb = cumulativeSize / (1024 ** 3)

        # Calculate block range info
        if blocksToProcess:
            firstBlockDate = blocksToProcess[0]['LastModified']
            lastBlockDate = blocksToProcess[-1]['LastModified']
        else:
            firstBlockDate = "N/A"
            lastBlockDate = "N/A"

        # Estimate costs
        requestCost = len(blocksToProcess) * 0.0004 / 1000  # $0.0004 per 1000 GET requests
        transferCost = totalSizeGb * 0.09 if totalSizeGb > 100 else 0  # First 100GB free
        totalEstimatedCost = requestCost + transferCost

        logger.info("=" * 70)
        logger.info(f"S3 DOWNLOAD PLAN:")
        logger.info(f"  Total blocks listed: {len(allBlocks):,}")
        logger.info(f"  Skipped (recent): {SKIP_FIRST_N_BLOCKS:,}")
        logger.info(f"  Blocks to download: {len(blocksToProcess):,}")
        logger.info(
            f"  Actual range: Block #{SKIP_FIRST_N_BLOCKS + 1:,} to #{SKIP_FIRST_N_BLOCKS + len(blocksToProcess):,}")
        logger.info(f"  Size to download: {totalSizeGb:.2f} GB")
        logger.info(f"  Date range: {lastBlockDate} to {firstBlockDate}")
        logger.info(f"  Estimated cost: ${totalEstimatedCost:.3f}")
        logger.info(f"    - Request cost: ${requestCost:.3f}")
        logger.info(f"    - Transfer cost: ${transferCost:.3f} (first 100GB free)")
        logger.info("=" * 70)

        if len(blocksToProcess) == 0:
            logger.warning("No blocks to download after skipping and size calculation")
            return 0

        # Ask for confirmation
        logger.info(f"Ready to download {len(blocksToProcess):,} historical blocks")
        logger.info("Starting in 5 seconds... (Ctrl+C to cancel)")
        await asyncio.sleep(5)

        # Process blocks with progress updates
        logger.info("Starting block download and processing...")
        userBatch = set()
        totalNewUsers = 0
        downloadedBytes = 0
        startTime = time.time()

        for i, block_obj in enumerate(blocksToProcess):
            if shutdown_event.is_set():
                logger.info("Shutdown requested, stopping...")
                break

            try:
                key = block_obj['Key']
                blockSizeMb = block_obj['Size'] / (1024 * 1024)

                # Log every 10th block
                if i % 10 == 0:
                    actualBlockNum = SKIP_FIRST_N_BLOCKS + i + 1
                    logger.info(f"[{i + 1}/{len(blocksToProcess)}] Processing block #{actualBlockNum:,}")

                # Download
                response = s3_client.get_object(
                    Bucket=bucket_name,
                    Key=key,
                    RequestPayer='requester'
                )
                content = response['Body'].read()
                downloadedBytes += len(content)

                # Decompress if needed
                if key.endswith('.lz4'):
                    content = lz4.frame.decompress(content)

                # Parse
                try:
                    if key.endswith('.rmp') or key.endswith('.rmp.lz4'):
                        blockData = msgpack.unpackb(content, raw=False)
                    else:
                        blockData = json.loads(content)
                except:
                    try:
                        blockData = json.loads(content)
                    except:
                        blockData = msgpack.unpackb(content, raw=False)

                # Extract users
                users = await extractAllUsers(blockData)
                userBatch.update(users)

                # Batch insert every 50 blocks
                if len(userBatch) >= 500 or (i % 50 == 0 and userBatch):
                    newCount, _ = await batchAddUsers(usersCollection, userBatch)
                    totalNewUsers += newCount
                    userBatch.clear()

                    # Progress update every 50 blocks
                    if i % 50 == 0:
                        downloadedGb = downloadedBytes / (1024 ** 3)
                        progressPct = (i + 1) / len(blocksToProcess) * 100
                        elapsed = time.time() - startTime
                        blocksPerSec = (i + 1) / elapsed
                        etaSeconds = (len(blocksToProcess) - i - 1) / blocksPerSec if blocksPerSec > 0 else 0
                        etaMinutes = etaSeconds / 60

                        logger.info("=" * 70)
                        logger.info(f"PROGRESS UPDATE:")
                        logger.info(f"  Current position: Block #{SKIP_FIRST_N_BLOCKS + i + 1:,}")
                        logger.info(f"  Progress: {i + 1:,}/{len(blocksToProcess):,} ({progressPct:.1f}%)")
                        logger.info(f"  Downloaded: {downloadedGb:.2f}/{Config.S3_MAX_DOWNLOAD_GB} GB")
                        logger.info(f"  New users: {totalNewUsers:,}")
                        logger.info(f"  Speed: {blocksPerSec:.2f} blocks/sec")
                        logger.info(f"  ETA: {etaMinutes:.1f} minutes")
                        logger.info("=" * 70)

            except Exception as e:
                logger.error(f"Error processing block {i + 1}: {e}")
                continue

        # Final batch
        if userBatch:
            logger.info(f"Saving final batch of {len(userBatch):,} users...")
            newCount, _ = await batchAddUsers(usersCollection, userBatch)
            totalNewUsers += newCount

        finalGb = downloadedBytes / (1024 ** 3)
        totalTime = time.time() - startTime
        actualRequestCost = len(blocksToProcess) * 0.0004 / 1000
        actualTransferCost = finalGb * 0.09 if finalGb > 100 else 0
        actualTotalCost = actualRequestCost + actualTransferCost

        logger.info("=" * 70)
        logger.info("S3 BACKFILL COMPLETE!")
        logger.info(f"  Block range: #{SKIP_FIRST_N_BLOCKS + 1:,} to #{SKIP_FIRST_N_BLOCKS + len(blocksToProcess):,}")
        logger.info(f"  Blocks processed: {len(blocksToProcess):,}")
        logger.info(f"  Downloaded: {finalGb:.2f} GB")
        logger.info(f"  New users: {totalNewUsers:,}")
        logger.info(f"  Time taken: {totalTime / 60:.1f} minutes")
        logger.info(f"  Actual cost: ${actualTotalCost:.3f}")
        logger.info("=" * 70)

        return totalNewUsers

    except Exception as e:
        logger.error(f"S3 backfill failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0


# REST API backfill (FREE alternative)
async def backfillFromRestApi(usersCollection):
    """FREE: Use REST API (no AWS needed)"""
    logger.info("Starting FREE REST API backfill...")
    rateLimiter = RateLimiter(maxCalls=30, period=60)

    coins = await getActiveCoins()
    totalNewUsers = 0

    async with aiohttp.ClientSession() as session:
        for coin in coins[:30]:
            try:
                await rateLimiter.acquire()

                payload = {"type": "recentTrades", "coin": coin}

                async with session.post(
                        Config.REST_API_URL,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        trades = await resp.json()
                        userBatch = set()

                        for trade in trades:
                            users = await extractAllUsers(trade)
                            userBatch.update(users)

                        if userBatch:
                            newCount, _ = await batchAddUsers(usersCollection, userBatch)
                            totalNewUsers += newCount
                            logger.info(f"{coin}: {newCount} new users")

            except Exception as e:
                logger.error(f"Error for {coin}: {e}")

    logger.info(f"REST backfill complete: {totalNewUsers} new users (FREE)")
    return totalNewUsers


# Real-time WebSocket
async def websocketWatcher(db):
    """Real-time trade tracking"""
    usersCollection = db["users"]

    coins = await getActiveCoins()
    coinsToMonitor = coins[:Config.MAX_COIN_SUBSCRIPTIONS]

    logger.info(f"Monitoring {len(coinsToMonitor)} coins")

    messageQueue = asyncio.Queue(maxsize=Config.QUEUE_MAX_SIZE)

    totalTrades = 0
    totalNewUsers = 0
    startTime = datetime.now(timezone.utc)

    async def processQueue():
        userBatch = set()
        lastBatchTime = datetime.now(timezone.utc)

        while not shutdown_event.is_set():
            try:
                try:
                    trade = await asyncio.wait_for(messageQueue.get(), timeout=Config.BATCH_TIMEOUT)
                    users = await extractAllUsers(trade)
                    userBatch.update(users)
                    messageQueue.task_done()
                except asyncio.TimeoutError:
                    pass

                currentTime = datetime.now(timezone.utc)
                timeElapsed = (currentTime - lastBatchTime).total_seconds()

                if len(userBatch) >= Config.BATCH_SIZE or (userBatch and timeElapsed >= Config.BATCH_TIMEOUT):
                    newCount, _ = await batchAddUsers(usersCollection, userBatch)
                    nonlocal totalNewUsers
                    totalNewUsers += newCount
                    userBatch.clear()
                    lastBatchTime = currentTime

            except Exception as e:
                logger.error(f"Queue error: {e}")
                await asyncio.sleep(1)

        if userBatch:
            await batchAddUsers(usersCollection, userBatch)

    processorTask = asyncio.create_task(processQueue())

    retryDelay = 5
    maxRetryDelay = 300

    while not shutdown_event.is_set():
        try:
            async with websockets.connect(Config.WS_URL, ping_interval=20, ping_timeout=10) as ws:
                logger.info("WebSocket connected")
                retryDelay = 5

                for coin in coinsToMonitor:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "trades", "coin": coin}
                    }))
                    await asyncio.sleep(0.01)

                logger.info(f"Subscribed to {len(coinsToMonitor)} coins")

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
                        tradeList = data.get('data', [])
                        if not isinstance(tradeList, list):
                            tradeList = [tradeList]

                        for trade in tradeList:
                            try:
                                messageQueue.put_nowait(trade)
                                totalTrades += 1

                                if totalTrades % 1000 == 0:
                                    elapsed = (datetime.now(timezone.utc) - startTime).total_seconds()
                                    throughput = totalTrades / elapsed if elapsed > 0 else 0
                                    logger.info(
                                        f"Stats: {totalTrades} trades, {totalNewUsers} new users, {throughput:.2f}/s")

                            except asyncio.QueueFull:
                                logger.warning("Queue full")

        except Exception as e:
            logger.error(f"WebSocket error: {e} - reconnecting in {retryDelay}s")

        if not shutdown_event.is_set():
            await asyncio.sleep(retryDelay)
            retryDelay = min(retryDelay * 2, maxRetryDelay)

    await processorTask


# Main
async def main():
    logger.info("=" * 70)
    logger.info("Hyperliquid User Tracker - Historical Backfill")
    logger.info("=" * 70)

    client = motor.motor_asyncio.AsyncIOMotorClient(Config.MONGO_URI)
    db = client["hyperliquid"]
    usersCollection = db["users"]

    await setupIndexes(db)

    # Historical backfill
    if Config.USE_S3_BACKFILL and HAS_S3_SUPPORT:
        await backfillFromS3Limited(usersCollection)
    else:
        await backfillFromRestApi(usersCollection)

    logger.info("Historical backfill complete. Shutting down...")
    client.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped")
