import aiohttp
import asyncio
from collections import Counter
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone

# --- Settings ---
MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME = "hyperliquid"
MILLIONAIRE_COLLECTION = "millionaires"
BIAS_COLLECTION = "bias_summaries"
HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"
TARGET_COINS = ["BTC", "ETH","HYPE"]
MAX_RETRIES = 3
PARALLEL = 10
RATE_LIMIT_DELAY = 0.10  # seconds

async def fetch_millionaires_wallets():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    millionaires_coll = db[MILLIONAIRE_COLLECTION]
    docs = await millionaires_coll.find({}, {"_id": 0, "wallet": 1}).to_list(None)
    return [d["wallet"] for d in docs if "wallet" in d]

async def fetch_positions(session, wallet):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                HYPERLIQUID_API,
                json={"type": "clearinghouseState", "user": wallet}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("assetPositions", [])
                elif resp.status == 422:
                    print(f"[{wallet}] ❌ Wallet not supported or invalid (422)")
                    return []
                else:
                    print(f"[{wallet}] Error: {resp.status}")
        except Exception as e:
            print(f"[{wallet}] Exception: {e}")

        wait_time = 2 ** attempt
        print(f"[{wallet}] Retry {attempt+1}/{MAX_RETRIES} in {wait_time}s...")
        await asyncio.sleep(wait_time)
    print(f"[{wallet}] ⚠️ Failed after {MAX_RETRIES} attempts.")
    return []

async def fetch_all_positions(wallets, session, parallel=PARALLEL):
    sema = asyncio.Semaphore(parallel)
    async def worker(wallet):
        async with sema:
            positions = await fetch_positions(session, wallet)
            return wallet, positions
    tasks = [worker(w) for w in wallets]
    results = await asyncio.gather(*tasks)
    return dict(results)

def summarize_bias(wallet_positions):
    bias_qty = {coin: Counter() for coin in TARGET_COINS}
    bias_val = {coin: Counter() for coin in TARGET_COINS}
    per_wallet = {}
    for wallet, positions in wallet_positions.items():
        w_qty = {coin: Counter() for coin in TARGET_COINS}
        w_val = {coin: Counter() for coin in TARGET_COINS}
        for pos_data in positions:
            pos = pos_data.get("position", {})
            coin = pos.get("coin")
            szi = float(pos.get("szi", 0))
            val = float(pos.get("positionValue", 0))
            if szi == 0 or val == 0 or coin not in TARGET_COINS:
                continue
            side = "B" if szi > 0 else "A"
            bias_qty[coin][side] += abs(szi)
            bias_val[coin][side] += val
            w_qty[coin][side] += abs(szi)
            w_val[coin][side] += val
        per_wallet[wallet] = {
            coin: {
                "long_sz": w_qty[coin].get("B", 0.0),
                "short_sz": w_qty[coin].get("A", 0.0),
                "long": w_val[coin].get("B", 0.0),
                "short": w_val[coin].get("A", 0.0)
            }
            for coin in TARGET_COINS
        }
    # Compute aggregate bias
    aggregate = {}
    for coin in TARGET_COINS:
        long_v = bias_val[coin].get("B", 0.0)
        short_v = bias_val[coin].get("A", 0.0)
        total_v = long_v + short_v
        long_pct = (long_v / total_v * 100) if total_v > 0 else 0
        short_pct = (short_v / total_v * 100) if total_v > 0 else 0
        direction = "Long" if long_v > short_v else "Short" if short_v > long_v else "Neutral"
        aggregate[coin] = {
            "long": long_v, "short": short_v,
            "long_pct": long_pct, "short_pct": short_pct,
            "direction": direction
        }
    return {
        "aggregate": aggregate,
        "per_wallet": per_wallet,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

async def save_bias_to_mongo(bias_summary):
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    coll = db[BIAS_COLLECTION]
    await coll.insert_one(bias_summary)

# --- Main job: update every 20 minutes ---
async def main():
    while True:
        try:
            print("Fetching latest wallet positions and computing bias summary...")
            wallets = await fetch_millionaires_wallets()
            async with aiohttp.ClientSession() as session:
                wallet_positions = await fetch_all_positions(wallets, session, parallel=PARALLEL)
            bias_summary = summarize_bias(wallet_positions)
            print("Bias summary saved at", bias_summary["timestamp"])
            await save_bias_to_mongo(bias_summary)
            for coin, stats in bias_summary["aggregate"].items():
                print(f"{coin}: {stats['direction']} | Long: ${stats['long']:.2f} ({stats['long_pct']:.1f}%) | Short: ${stats['short']:.2f} ({stats['short_pct']:.1f}%)")
            print("---- Next update in 20 minutes ----")
            await asyncio.sleep(20*60)
        except Exception as e:
            print(f"[ERROR] {e} -- sleeping 2 minutes before retry")
            await asyncio.sleep(120)


if __name__ == "__main__":
    asyncio.run(main())
