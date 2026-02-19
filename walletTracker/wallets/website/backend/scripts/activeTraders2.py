import asyncio
import json
import logging
import websockets
import motor.motor_asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
from dotenv import load_dotenv
import aiohttp
import signal
from collections import deque
import time
from pymongo import UpdateOne


# Resolve project root (parent of this file's folder)
BASE_DIR = Path(__file__).resolve().parent.parent  # backend/.. = website/
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


# Configuration Management
class Config:
    MONGO_URI = os.getenv("MONGO_URI")
    DB_NAME = os.getenv("DB_NAME", "hyperliquid")
    USERS_COLLECTION = "users"
    MONITOR_COLLECTION = "user_monitor"
    METRICS_COLLECTION = "system_metrics"
    WS_URL = os.getenv("WS_URL", "wss://rpc.hyperliquid.xyz/ws")
    REST_API_URL = os.getenv("REST_API_URL", "https://api.hyperliquid.xyz/info")
    MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", 86400))  # 24h default
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", 100))
    BATCH_TIMEOUT = int(os.getenv("BATCH_TIMEOUT", 5))
    QUEUE_MAX_SIZE = int(os.getenv("QUEUE_MAX_SIZE", 10000))

    @classmethod
    def validate(cls):
        if not cls.MONGO_URI:
            raise ValueError("MONGO_URI environment variable required")


# Validate configuration
Config.validate()

# Logger setup
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ExplorerTxTracker")

# Graceful shutdown handler
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
            await asyncio.sleep(sleep_time)
            return await self.acquire()

        self.calls.append(now)


# Extract all possible user addresses from transaction data
async def extract_all_users(tx_data):
    """Extract all possible user addresses from transaction data"""
    users = set()

    # Common user fields in Hyperliquid transactions
    user_fields = [
        'user', 'wallet', 'address', 'from', 'to', 'sender',
        'receiver', 'maker', 'taker', 'trader', 'account', 'owner'
    ]

    def extract_recursive(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in user_fields and isinstance(value, str) and value:
                    # Basic validation: Ethereum addresses are typically 42 chars (0x + 40 hex)
                    if value.startswith('0x') and len(value) == 42:
                        users.add(value)
                else:
                    extract_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                extract_recursive(item)

    extract_recursive(tx_data)
    return users


# Batch insert users for better performance
async def batch_add_users(users_collection, user_batch):
    """Bulk insert users for better performance"""
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
                        "first_seen": current_time,
                        "is_millionaire": False
                    },
                    "$set": {
                        "last_seen": current_time
                    },
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
            logger.info(f"\033[92m✓ Batch saved {new_users} new users, updated {updated_users} existing\033[0m")

        return new_users, updated_users

    except Exception as e:
        logger.error(f"Batch insert error: {e}")
        return 0, 0

# Log system metrics
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


# Setup database indexes
async def setup_indexes(db):
    """Create indexes for performance"""
    try:
        users_collection = db[Config.USERS_COLLECTION]
        await users_collection.create_index("user", unique=True)
        await users_collection.create_index("is_millionaire")
        await users_collection.create_index([("last_seen", -1)])
        await users_collection.create_index([("tx_count", -1)])
        await users_collection.create_index([("first_seen", -1)])

        monitor_collection = db[Config.MONITOR_COLLECTION]
        await monitor_collection.create_index([("timestamp", -1)])

        metrics_collection = db[Config.METRICS_COLLECTION]
        await metrics_collection.create_index([("timestamp", -1)])
        await metrics_collection.create_index("metric_type")

        logger.info("\033[94m✓ Database indexes created/verified\033[0m")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")


# Historical backfill of users
async def backfill_historical_users(users_collection):
    """One-time historical user extraction via REST API"""
    logger.info("Starting historical backfill...")
    rate_limiter = RateLimiter(max_calls=10, period=60)

    async with aiohttp.ClientSession() as session:
        try:
            await rate_limiter.acquire()

            # Request historical transactions from Hyperliquid REST API
            payload = {"type": "recentTxs", "limit": 10000}

            async with session.post(
                    Config.REST_API_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    user_batch = set()

                    # Handle both list and dict responses
                    transactions = data if isinstance(data, list) else data.get('transactions', [])

                    for tx in transactions:
                        user_addresses = await extract_all_users(tx)
                        user_batch.update(user_addresses)

                    new_count, updated_count = await batch_add_users(users_collection, user_batch)
                    logger.info(f"\033[92m✓ Backfill complete: {new_count} new users, {updated_count} updated\033[0m")
                else:
                    logger.warning(f"Backfill request returned status {resp.status}")

        except asyncio.TimeoutError:
            logger.warning("Backfill request timed out, skipping...")
        except Exception as e:
            logger.error(f"Backfill error: {e}")


# Main WebSocket watcher with all features
async def websocket_watcher(db):
    """Persistent websocket watcher with batching and queueing"""
    users_collection = db[Config.USERS_COLLECTION]

    # Message queue for peak loads
    message_queue = asyncio.Queue(maxsize=Config.QUEUE_MAX_SIZE)

    # Metrics tracking
    total_tx_processed = 0
    total_users_saved = 0
    start_time = datetime.now(timezone.utc)

    async def process_queue():
        """Background task to process queued messages"""
        user_batch = set()
        last_batch_time = datetime.now(timezone.utc)

        while not shutdown_event.is_set():
            try:
                # Get message with timeout to periodically flush batch
                try:
                    tx = await asyncio.wait_for(message_queue.get(), timeout=Config.BATCH_TIMEOUT)
                    user_addresses = await extract_all_users(tx)
                    user_batch.update(user_addresses)
                    message_queue.task_done()
                except asyncio.TimeoutError:
                    pass  # Timeout triggers batch flush check

                current_time = datetime.now(timezone.utc)
                time_elapsed = (current_time - last_batch_time).total_seconds()

                # Flush when batch is large enough or timeout reached
                if len(user_batch) >= Config.BATCH_SIZE or (user_batch and time_elapsed >= Config.BATCH_TIMEOUT):
                    new_count, _ = await batch_add_users(users_collection, user_batch)
                    nonlocal total_users_saved
                    total_users_saved += new_count
                    user_batch.clear()
                    last_batch_time = current_time

            except Exception as e:
                logger.error(f"Queue processing error: {e}")
                await asyncio.sleep(1)

        # Flush remaining batch on shutdown
        if user_batch:
            await batch_add_users(users_collection, user_batch)
            logger.info("Flushed remaining batch on shutdown")

    # Start queue processor
    processor_task = asyncio.create_task(process_queue())

    # WebSocket connection with retry logic
    retry_delay = 5
    max_retry_delay = 300  # 5 minutes

    # Subscription types to capture different user activities
    subscriptions = [
        {"type": "explorerTxs"},
    ]

    while not shutdown_event.is_set():
        try:
            async with websockets.connect(
                    Config.WS_URL,
                    origin="https://app.hyperliquid.xyz",
                    ping_interval=20,
                    ping_timeout=10
            ) as ws:
                logger.info("\033[94m✓ WebSocket connection opened\033[0m")
                retry_delay = 5  # Reset on successful connection

                # Subscribe to all streams
                for sub in subscriptions:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": sub
                    }))
                    logger.info(f"Subscribed to: {sub['type']}")

                async for message in ws:
                    if shutdown_event.is_set():
                        break

                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError as e:
                        logger.warning(f"JSON decode error: {e}")
                        continue

                    # Handle both list and dict responses
                    transactions = []
                    if isinstance(data, list):
                        transactions = data
                    elif isinstance(data, dict) and 'data' in data:
                        transactions = [data['data']] if not isinstance(data['data'], list) else data['data']
                    elif isinstance(data, dict):
                        transactions = [data]

                    for tx in transactions:
                        try:
                            message_queue.put_nowait(tx)
                            total_tx_processed += 1

                            # Log metrics every 1000 transactions
                            if total_tx_processed % 1000 == 0:
                                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                                throughput = total_tx_processed / elapsed if elapsed > 0 else 0
                                await log_metrics(
                                    db,
                                    "tx_throughput",
                                    throughput,
                                    {
                                        "total_tx": total_tx_processed,
                                        "total_users": total_users_saved,
                                        "queue_size": message_queue.qsize()
                                    }
                                )
                                logger.info(f"\033[96m Stats: {total_tx_processed} tx processed, "
                                            f"{total_users_saved} new users, "
                                            f"{throughput:.2f} tx/s, "
                                            f"queue: {message_queue.qsize()}\033[0m")

                        except asyncio.QueueFull:
                            logger.warning("  Queue full, dropping transaction")
                            await log_metrics(db, "queue_full_events", 1)

        except websockets.exceptions.ConnectionClosed as e:
            logger.error(f"WebSocket closed: {e} - reconnecting in {retry_delay}s...")
        except Exception as e:
            logger.error(f"WebSocket error: {e} - reconnecting in {retry_delay}s...")

        if not shutdown_event.is_set():
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)  # Exponential backoff

    # Wait for queue processor to finish
    await processor_task
    logger.info("WebSocket watcher stopped")


# Monitoring/analytics: records user count periodically
async def daily_monitor(db):
    """Monitor and log user statistics"""
    users_collection = db[Config.USERS_COLLECTION]
    monitor_collection = db[Config.MONITOR_COLLECTION]

    while not shutdown_event.is_set():
        try:
            ts = datetime.now(timezone.utc).isoformat()
            user_count = await users_collection.count_documents({})
            millionaire_count = await users_collection.count_documents({"is_millionaire": True})

            doc = {
                "timestamp": ts,
                "user_count": user_count,
                "millionaire_count": millionaire_count
            }
            await monitor_collection.insert_one(doc)
            logger.info(
                f"\033[94m📈 MONITOR: {user_count} total users ({millionaire_count} millionaires) at {ts}\033[0m")

            # Also log as metric
            await log_metrics(db, "total_users", user_count, {"millionaires": millionaire_count})

        except Exception as e:
            logger.error(f"Monitor error: {e}")

        # Sleep in chunks to allow graceful shutdown
        for _ in range(Config.MONITOR_INTERVAL):
            if shutdown_event.is_set():
                break
            await asyncio.sleep(1)

    logger.info("Monitor stopped")


# Entry: run websocket watcher and monitor concurrently
async def main():
    logger.info("🚀 Starting Hyperliquid User Tracker")
    logger.info(f"Configuration: DB={Config.DB_NAME}, Batch={Config.BATCH_SIZE}, Queue={Config.QUEUE_MAX_SIZE}")

    # Connect to MongoDB
    client = motor.motor_asyncio.AsyncIOMotorClient(Config.MONGO_URI)
    db = client[Config.DB_NAME]

    # Setup database indexes
    await setup_indexes(db)

    # Backfill historical data
    users_collection = db[Config.USERS_COLLECTION]
    await backfill_historical_users(users_collection)

    # Start real-time tracking and monitoring
    try:
        await asyncio.gather(
            websocket_watcher(db),
            daily_monitor(db)
        )
    except asyncio.CancelledError:
        logger.info("Tasks cancelled")
    finally:
        logger.info("Shutting down gracefully...")
        client.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt")
    finally:
        logger.info("✓ Application stopped")
