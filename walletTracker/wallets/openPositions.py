import asyncio
import aiohttp
import json
from motor.motor_asyncio import AsyncIOMotorClient
from collections import Counter

MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME, COLL = "hyperliquid", "millionaires"
API_URL = "https://api.hyperliquid.xyz/info"
COINS = ["BTC", "ETH", "HYPE"]
PARALLEL = 10
RETRY = 3

async def fetch_wallets():
    cli = AsyncIOMotorClient(MONGO_URI)
    docs = await cli[DB_NAME][COLL].find({}, {"_id": 0, "wallet": 1}).to_list(None)
    return [doc["wallet"] for doc in docs if "wallet" in doc]

async def fetch_position(session, wallet):
    for attempt in range(RETRY):
        try:
            async with session.post(API_URL, json={"type": "clearinghouseState", "user": wallet}) as resp:
                if resp.status == 200:
                    js = await resp.json()
                    return wallet, js.get("assetPositions", [])
                elif resp.status == 422:
                    print(f"[{wallet}] Invalid.")
                    return wallet, []
                else:
                    print(f"[{wallet}] Status {resp.status}")
        except Exception as e:
            print(f"[{wallet}] Exception: {e}")
        await asyncio.sleep(2**attempt)
    print(f"[{wallet}] Failed after retries")
    return wallet, []

async def process_wallets(wallets):
    bias_qty = {coin: Counter() for coin in COINS}
    bias_val = {coin: Counter() for coin in COINS}
    wallet_bias = {}
    async with aiohttp.ClientSession() as session:
        sema = asyncio.Semaphore(PARALLEL)
        async def worker(wallet):
            async with sema:
                w, positions = await fetch_position(session, wallet)
                per_qty = {coin: Counter() for coin in COINS}
                per_val = {coin: Counter() for coin in COINS}
                for pos in positions:
                    coin = pos.get("position", {}).get("coin")
                    szi = float(pos.get("position", {}).get("szi", 0))
                    val = float(pos.get("position", {}).get("positionValue", 0))
                    if coin in bias_qty and szi and val:
                        side = "B" if szi > 0 else "A"
                        bias_qty[coin][side] += abs(szi)
                        bias_val[coin][side] += val
                        per_qty[coin][side] += abs(szi)
                        per_val[coin][side] += val
                wallet_bias[wallet] = {}
                for coin in COINS:
                    long_val = per_val[coin].get("B", 0.0)
                    short_val = per_val[coin].get("A", 0.0)
                    total_val = long_val + short_val
                    long_pct = (long_val / total_val * 100) if total_val > 0 else 0
                    short_pct = (short_val / total_val * 100) if total_val > 0 else 0
                    direction = (
                        "Long" if long_val > short_val else
                        "Short" if short_val > long_val else
                        "Neutral"
                    )
                    wallet_bias[wallet][coin] = {
                        "long": long_val,
                        "short": short_val,
                        "long_pct": long_pct,
                        "short_pct": short_pct,
                        "direction": direction
                    }
        tasks = [worker(w) for w in wallets]
        for i in range(0, len(tasks), PARALLEL):
            await asyncio.gather(*tasks[i:i+PARALLEL])
            await asyncio.sleep(1)

    aggregate_bias = {}
    for coin in COINS:
        long_val = bias_val[coin].get("B", 0.0)
        short_val = bias_val[coin].get("A", 0.0)
        total_val = long_val + short_val
        long_pct = (long_val / total_val * 100) if total_val > 0 else 0
        short_pct = (short_val / total_val * 100) if total_val > 0 else 0
        direction = (
            "Long" if long_val > short_val else
            "Short" if short_val > long_val else
            "Neutral"
        )
        aggregate_bias[coin] = {
            "long": long_val, "short": short_val,
            "long_pct": long_pct, "short_pct": short_pct,
            "direction": direction
        }
    return wallet_bias, aggregate_bias

def save_bias(wallet_bias, aggregate_bias):
    out = {
        "wallet_bias": wallet_bias,
        "aggregate_bias": aggregate_bias
    }
    with open("bias_summary.json", "w") as f:
        json.dump(out, f)

async def rebalance_and_save():
    wallets = await fetch_wallets()
    print(f"Processing {len(wallets)} wallets...")
    wallet_bias, aggregate_bias = await process_wallets(wallets)
    save_bias(wallet_bias, aggregate_bias)
    print("Bias summary saved to bias_summary.json")

async def main():
    while True:
        await rebalance_and_save()
        await asyncio.sleep(60)  # Refresh every 60s

if __name__ == "__main__":
    asyncio.run(main())
