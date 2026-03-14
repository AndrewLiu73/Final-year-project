import aiohttp
import asyncio
from collections import Counter
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

MONGO_URI              = os.getenv("MONGO_URI")
HYPERLIQUID_API        = "https://api.hyperliquid.xyz/info"
TARGET_COINS           = ["BTC", "ETH", "HYPE"]
MAX_RETRIES            = 3
PARALLEL               = 10
RATE_LIMIT_DELAY       = 0.10


async def fetchMillionairesWallets():
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client["hyperliquid"]
    coll   = db["millionaires"]
    docs   = await coll.find({}, {"_id": 0, "wallet": 1}).to_list(None)
    return [d["wallet"] for d in docs if "wallet" in d]


async def fetchPositions(session, wallet):
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
                    print(f"[{wallet}] Wallet not supported or invalid (422)")
                    return []
                else:
                    print(f"[{wallet}] Error: {resp.status}")
        except Exception as e:
            print(f"[{wallet}] Exception: {e}")

        waitTime = 2 ** attempt
        print(f"[{wallet}] Retry {attempt + 1}/{MAX_RETRIES} in {waitTime}s...")
        await asyncio.sleep(waitTime)

    print(f"[{wallet}] Failed after {MAX_RETRIES} attempts.")
    return []


async def fetchAllPositions(wallets, session, parallel=PARALLEL):
    sema = asyncio.Semaphore(parallel)

    async def worker(wallet):
        async with sema:
            positions = await fetchPositions(session, wallet)
            return wallet, positions

    tasks   = [worker(w) for w in wallets]
    results = await asyncio.gather(*tasks)
    return dict(results)


def summarizeBias(walletPositions):
    biasQty   = {coin: Counter() for coin in TARGET_COINS}
    biasVal   = {coin: Counter() for coin in TARGET_COINS}
    perWallet = {}

    for wallet, positions in walletPositions.items():
        wQty = {coin: Counter() for coin in TARGET_COINS}
        wVal = {coin: Counter() for coin in TARGET_COINS}

        for posData in positions:
            pos  = posData.get("position", {})
            coin = pos.get("coin")
            szi  = float(pos.get("szi", 0))
            val  = float(pos.get("positionValue", 0))

            if szi == 0 or val == 0 or coin not in TARGET_COINS:
                continue

            side = "B" if szi > 0 else "A"
            biasQty[coin][side] += abs(szi)
            biasVal[coin][side] += val
            wQty[coin][side]    += abs(szi)
            wVal[coin][side]    += val

        perWallet[wallet] = {
            coin: {
                "long_sz":  wQty[coin].get("B", 0.0),
                "short_sz": wQty[coin].get("A", 0.0),
                "long":     wVal[coin].get("B", 0.0),
                "short":    wVal[coin].get("A", 0.0),
            }
            for coin in TARGET_COINS
        }

    aggregate = {}
    for coin in TARGET_COINS:
        longV  = biasVal[coin].get("B", 0.0)
        shortV = biasVal[coin].get("A", 0.0)
        totalV = longV + shortV

        longPct  = (longV  / totalV * 100) if totalV > 0 else 0
        shortPct = (shortV / totalV * 100) if totalV > 0 else 0
        direction = (
            "Long"    if longV > shortV else
            "Short"   if shortV > longV else
            "Neutral"
        )

        longWallets  = sum(1 for w in perWallet.values() if w[coin]["long"]  > 0)
        shortWallets = sum(1 for w in perWallet.values() if w[coin]["short"] > 0)
        totalWallets = longWallets + shortWallets

        aggregate[coin] = {
            "long":          longV,
            "short":         shortV,
            "long_pct":      longPct,
            "short_pct":     shortPct,
            "direction":     direction,
            "long_wallets":  longWallets,
            "short_wallets": shortWallets,
            "total_wallets": totalWallets,
        }

    return {
        "aggregate": aggregate,
        "per_wallet": perWallet,
        "timestamp":  datetime.now(timezone.utc).isoformat()
    }


async def saveBiasToMongo(biasSummary):
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client["hyperliquid"]
    coll   = db["bias_summaries"]
    await coll.insert_one(biasSummary)


async def main():
    while True:
        try:
            print("Fetching latest wallet positions and computing bias summary...")
            wallets = await fetchMillionairesWallets()

            async with aiohttp.ClientSession() as session:
                walletPositions = await fetchAllPositions(wallets, session, parallel=PARALLEL)

            biasSummary = summarizeBias(walletPositions)
            await saveBiasToMongo(biasSummary)

            print(f"Bias summary saved at {biasSummary['timestamp']}")
            for coin, stats in biasSummary["aggregate"].items():
                print(
                    f"{coin}: {stats['direction']} | "
                    f"Long: ${stats['long']:.2f} ({stats['long_pct']:.1f}%) "
                    f"[{stats['long_wallets']} wallets] | "
                    f"Short: ${stats['short']:.2f} ({stats['short_pct']:.1f}%) "
                    f"[{stats['short_wallets']} wallets]"
                )

            print("Next update in 24 hours")
            await asyncio.sleep(24 * 60 * 60)

        except Exception as e:
            print(f"[ERROR] {e} -- sleeping 2 minutes before retry")
            await asyncio.sleep(120)


if __name__ == "__main__":
    asyncio.run(main())
