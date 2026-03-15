import asyncio
import httpx
import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MONGO_URI       = os.getenv("MONGO_URI")
TARGET_COINS    = ["BTC", "ETH", "HYPE"]
SPIKE_THRESHOLD = 5.0


def get_trend_label(oi_chg, px_chg):
    oi_up, oi_down = oi_chg > 3.0, oi_chg < -3.0
    px_up, px_down = px_chg > 1.0, px_chg < -1.0
    if oi_up and px_up:    return "Building Long"
    if oi_up and px_down:  return "Squeeze Risk"
    if oi_up:              return "Crowded / Fragile"
    if oi_down and px_up:  return "Short Covering"
    if oi_down and px_down: return "Deleveraging"
    return "Neutral"


async def fetch_binance_oi(client, coin):
    sym = f"{coin}USDT"
    r  = await client.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}", timeout=8)
    pr = await client.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}", timeout=8)
    if r.status_code == pr.status_code == 200:
        px = float(pr.json().get("markPrice", 0))
        return float(r.json().get("openInterest", 0)) * px, px


async def fetch_bybit_oi(client, coin):
    sym = f"{coin}USDT"
    r  = await client.get(f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={sym}&intervalTime=5min&limit=1", timeout=8)
    pr = await client.get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}", timeout=8)
    if r.status_code == pr.status_code == 200:
        items   = r.json().get("result", {}).get("list", [])
        tickers = pr.json().get("result", {}).get("list", [])
        if items and tickers:
            px = float(tickers[0].get("markPrice", 0))
            return float(items[0].get("openInterest", 0)) * px, px


async def fetch_okx_oi(client, coin):
    inst = f"{coin}-USDT-SWAP"
    r  = await client.get(f"https://www.okx.com/api/v5/public/open-interest?instId={inst}", timeout=8)
    pr = await client.get(f"https://www.okx.com/api/v5/public/mark-price?instId={inst}", timeout=8)
    if r.status_code == pr.status_code == 200:
        items  = r.json().get("data", [])
        pitems = pr.json().get("data", [])
        if items and pitems:
            return float(items[0].get("oiUsd", 0)), float(pitems[0].get("markPx", 0))


async def fetch_deribit_oi(client, coin):
    r = await client.get(f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={coin}&kind=future", timeout=8)
    if r.status_code == 200:
        results = r.json().get("result", [])
        if results:
            total_oi = sum(float(i.get("open_interest", 0)) for i in results if i.get("open_interest"))
            perp = next((i for i in results if f"{coin}-PERPETUAL" in i.get("instrument_name", "")), results[0])
            return total_oi, float(perp.get("mark_price", 0))


async def fetch_hyperliquid_oi(client, coin):
    r = await client.post("https://api.hyperliquid.xyz/info", json={"type": "metaAndAssetCtxs"}, timeout=8)
    if r.status_code == 200:
        meta, ctxs = r.json()
        for i, asset in enumerate(meta["universe"]):
            if asset["name"] == coin:
                px = float(ctxs[i].get("markPx", 0))
                return float(ctxs[i].get("openInterest", 0)) * px, px


async def upsert_oi(db, exchange, coin, oi_usd, mark_px):
    if not oi_usd or not mark_px:
        return

    coll, now = db["exchange_oi"], datetime.now(timezone.utc)
    existing  = await coll.find_one({"exchange": exchange, "coin": coin})

    if existing:
        ts = existing.get("timestamp_30min")
        if ts:
            if isinstance(ts, str): ts = datetime.fromisoformat(ts)
            elapsed = (now - ts).total_seconds()
        else:
            elapsed = 9999
        if elapsed >= 1800:
            oi_30, px_30, ts_new = existing.get("oi_usd", oi_usd), existing.get("mark_px", mark_px), now
        else:
            oi_30  = existing.get("oi_30min_ago", existing.get("oi_usd", oi_usd))
            px_30  = existing.get("px_30min_ago", existing.get("mark_px", mark_px))
            ts_new = ts if ts else now
    else:
        oi_30, px_30, ts_new = oi_usd, mark_px, now

    oi_chg = (oi_usd - oi_30) / oi_30 * 100 if oi_30 > 0 else 0
    px_chg = (mark_px - px_30) / px_30 * 100 if px_30 > 0 else 0
    trend  = get_trend_label(oi_chg, px_chg)

    if abs(oi_chg) >= SPIKE_THRESHOLD:
        print(f"[SPIKE] {exchange} {coin}: ${oi_30/1e9:.2f}B -> ${oi_usd/1e9:.2f}B ({oi_chg:+.1f}%) | {trend}")

    await coll.update_one(
        {"exchange": exchange, "coin": coin},
        {"$set": {"exchange": exchange, "coin": coin, "oi_usd": oi_usd, "mark_px": mark_px,
                  "oi_30min_ago": oi_30, "px_30min_ago": px_30,
                  "change_pct_30min": round(oi_chg, 2), "px_change_30min": round(px_chg, 2),
                  "trend_label": trend, "timestamp_30min": ts_new.isoformat(), "timestamp": now.isoformat()}},
        upsert=True
    )
    print(f"[{exchange}] {coin}: ${oi_usd/1e9:.3f}B | OI {oi_chg:+.1f}% | PX {px_chg:+.1f}% | {trend}")


async def main():
    db = AsyncIOMotorClient(MONGO_URI)["hyperliquid"]
    await db["exchange_oi"].create_index([("exchange", 1), ("coin", 1)], unique=True)

    fetchers   = [fetch_binance_oi, fetch_bybit_oi, fetch_okx_oi, fetch_deribit_oi, fetch_hyperliquid_oi]
    exchanges  = ["Binance", "Bybit", "OKX", "Deribit", "Hyperliquid"]

    while True:
        async with httpx.AsyncClient() as client:
            for coin in TARGET_COINS:
                for exchange, result in zip(exchanges, await asyncio.gather(*[f(client, coin) for f in fetchers])):
                    if result:
                        await upsert_oi(db, exchange, coin, *result)
        await asyncio.sleep(5 * 60)


if __name__ == "__main__":
    asyncio.run(main())
