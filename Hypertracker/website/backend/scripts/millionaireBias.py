import aiohttp
import asyncio
from collections import Counter
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MONGO_URI     = os.getenv("MONGO_URI")
HL_API        = "https://api.hyperliquid.xyz/info"
TARGET_COINS  = ["BTC", "ETH", "HYPE"]
MAX_RETRIES   = 3
PARALLEL      = 10


def db():
    return AsyncIOMotorClient(MONGO_URI)["hyperliquid"]


async def fetch_wallets():
    docs = await db()["millionaires"].find({}, {"_id": 0, "wallet": 1}).to_list(None)
    return [d["wallet"] for d in docs if "wallet" in d]


async def fetch_positions(session, wallet):
    for attempt in range(MAX_RETRIES):
        async with session.post(HL_API, json={"type": "clearinghouseState", "user": wallet}) as r:
            if r.status == 200:
                return (await r.json()).get("assetPositions", [])
            if r.status == 422:
                return []
        await asyncio.sleep(2 ** attempt)
    return []


async def fetch_all(wallets, session):
    sema = asyncio.Semaphore(PARALLEL)
    async def worker(w):
        async with sema:
            return w, await fetch_positions(session, w)
    return dict(await asyncio.gather(*[worker(w) for w in wallets]))


def summarize(wallet_positions):
    bias_val   = {c: Counter() for c in TARGET_COINS}
    per_wallet = {}

    for wallet, positions in wallet_positions.items():
        w_val = {c: Counter() for c in TARGET_COINS}
        for pd in positions:
            pos  = pd.get("position", {})
            coin = pos.get("coin")
            szi  = float(pos.get("szi", 0))
            val  = float(pos.get("positionValue", 0))
            if not szi or not val or coin not in TARGET_COINS:
                continue
            side = "B" if szi > 0 else "A"
            bias_val[coin][side] += val
            w_val[coin][side]    += val

        per_wallet[wallet] = {
            c: {"long": w_val[c].get("B", 0.0), "short": w_val[c].get("A", 0.0)}
            for c in TARGET_COINS
        }

    aggregate = {}
    for coin in TARGET_COINS:
        lv, sv  = bias_val[coin].get("B", 0.0), bias_val[coin].get("A", 0.0)
        total   = lv + sv
        aggregate[coin] = {
            "long":          lv,
            "short":         sv,
            "long_pct":      lv / total * 100 if total else 0,
            "short_pct":     sv / total * 100 if total else 0,
            "direction":     "Long" if lv > sv else "Short" if sv > lv else "Neutral",
            "long_wallets":  sum(1 for w in per_wallet.values() if w[coin]["long"]  > 0),
            "short_wallets": sum(1 for w in per_wallet.values() if w[coin]["short"] > 0),
        }

    return {"aggregate": aggregate, "per_wallet": per_wallet, "timestamp": datetime.now(timezone.utc).isoformat()}


async def main():
    while True:
        wallets = await fetch_wallets()
        async with aiohttp.ClientSession() as session:
            summary = summarize(await fetch_all(wallets, session))

        await db()["bias_summaries"].insert_one(summary)

        for coin, s in summary["aggregate"].items():
            print(f"{coin}: {s['direction']} | Long: ${s['long']:.2f} ({s['long_pct']:.1f}%) [{s['long_wallets']}w] | "
                  f"Short: ${s['short']:.2f} ({s['short_pct']:.1f}%) [{s['short_wallets']}w]")

        await asyncio.sleep(24 * 60 * 60)


if __name__ == "__main__":
    asyncio.run(main())
