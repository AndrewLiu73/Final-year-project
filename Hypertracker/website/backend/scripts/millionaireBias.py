import asyncio
import json
from collections import Counter
# from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from pathlib import Path

import httpx

from sqlite_db import get_async_connection
from hyperliquid_client import WEIGHT_BUDGETS, WeightLimiter, post_info

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# MONGO_URI    = os.getenv("MONGO_URI")
TARGET_COINS  = ["BTC", "ETH", "HYPE"]
MAX_RETRIES   = 3
PARALLEL      = 10

# this process's fixed slice of the shared 1200/min Hyperliquid budget — see
# hyperliquid_client.WEIGHT_BUDGETS for why it's not the full 1200.
HL_LIMITER = WeightLimiter(WEIGHT_BUDGETS["millionaire_bias"])


async def db():
    # return AsyncIOMotorClient(MONGO_URI)["hyperliquid"]
    return await get_async_connection()


async def fetch_wallets():
    conn = await db()
    # docs = await db()["millionaires"].find({}, {"_id": 0, "wallet": 1}).to_list(None)
    # return [d["wallet"] for d in docs if "wallet" in d]
    cursor = await conn.execute("SELECT wallet FROM millionaires")
    rows = await cursor.fetchall()
    await conn.close()
    return [row["wallet"] for row in rows]


async def fetch_positions(client, wallet):
    data = await post_info(client, HL_LIMITER, {"type": "clearinghouseState", "user": wallet}, retries=MAX_RETRIES)
    return (data or {}).get("assetPositions", [])


async def fetch_all(wallets, client):
    sema = asyncio.Semaphore(PARALLEL)
    async def worker(w):
        async with sema:
            return w, await fetch_positions(client, w)
    return dict(await asyncio.gather(*[worker(w) for w in wallets]))


def summarise(wallet_positions):
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

        longs = 0
        shorts = 0

        for w in per_wallet.values():
            wl = w[coin]["long"]
            ws = w[coin]["short"]

            if wl > ws:
                longs += 1
            elif ws > wl:
                shorts += 1
        aggregate[coin] = {
            "long":          lv,
            "short":         sv,
            "long_pct":      lv / total * 100 if total else 0,
            "short_pct":     sv / total * 100 if total else 0,
            "direction":     "Long" if lv > sv else "Short" if sv > lv else "Neutral",
            "long_wallets":  sum(1 for w in per_wallet.values() if w[coin]["long"]  > 0),
            "short_wallets": sum(1 for w in per_wallet.values() if w[coin]["short"] > 0),
            "longs": longs,
            "shorts": shorts,
        }

    return {"aggregate": aggregate, "per_wallet": per_wallet, "timestamp": datetime.now(timezone.utc).isoformat()}


async def main():
    while True:
        wallets = await fetch_wallets()
        async with httpx.AsyncClient() as client:
            summary = summarise(await fetch_all(wallets, client))

        # await db()["bias_summaries"].insert_one(summary)
        conn = await db()
        await conn.execute(
            "INSERT INTO bias_summaries (timestamp, data) VALUES (?, ?)",
            (summary["timestamp"], json.dumps(summary)),
        )
        await conn.commit()
        await conn.close()

        for coin, s in summary["aggregate"].items():
            print(f"{coin}: {s['direction']} | Long: ${s['long']:.2f} ({s['long_pct']:.1f}%) [{s['long_wallets']}w] | "
                  f"Short: ${s['short']:.2f} ({s['short_pct']:.1f}%) [{s['short_wallets']}w]")

        await asyncio.sleep(24 * 60 * 60)


if __name__ == "__main__":
    asyncio.run(main())
