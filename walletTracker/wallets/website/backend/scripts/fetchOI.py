import asyncio
import httpx
import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

MONGO_URI       = os.getenv("MONGO_URI")

TARGET_COINS    = ["BTC", "ETH" ,"HYPE"]
SPIKE_THRESHOLD = 5.0


# ── trend label ───────────────────────────────────────────────────────────────

def getTrendLabel(oiChg: float, pxChg: float) -> str:
    oiUp   = oiChg >  3.0
    oiDown = oiChg < -3.0
    pxUp   = pxChg >  1.0
    pxDown = pxChg < -1.0

    if oiUp and pxUp:
        return "Building Long"
    if oiUp and pxDown:
        return "Squeeze Risk"
    if oiUp and not pxUp and not pxDown:
        return "Crowded / Fragile"
    if oiDown and pxUp:
        return "Short Covering"
    if oiDown and pxDown:
        return "Deleveraging"
    return "Neutral"


# ── fetchers — all return (oiUsd, markPx) or None ────────────────────────────

async def fetchBinanceOi(client, coin):
    symbol = f"{coin}USDT"
    url    = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
    try:
        r = await client.get(url, timeout=8)
        if r.status_code == 200:
            data     = r.json()
            oiCoins  = float(data.get("openInterest", 0))
            priceUrl = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
            pr = await client.get(priceUrl, timeout=8)
            priceData = pr.json() if pr.status_code == 200 else {}
            markPx = float(priceData.get("markPrice", 0))
            return oiCoins * markPx, markPx
    except Exception as e:
        print(f"[Binance {coin}] {e}")
    return None


async def fetchBybitOi(client, coin):
    symbol   = f"{coin}USDT"
    oiUrl    = (
        "https://api.bybit.com/v5/market/open-interest"
        f"?category=linear&symbol={symbol}&intervalTime=5min&limit=1"
    )
    priceUrl = (
        "https://api.bybit.com/v5/market/tickers"
        f"?category=linear&symbol={symbol}"
    )
    try:
        r = await client.get(oiUrl, timeout=8)
        if r.status_code != 200:
            return None
        oiData = r.json()
        if oiData.get("retCode", -1) != 0:
            return None
        items = oiData.get("result", {}).get("list", [])
        if not items:
            return None
        oiCoins = float(items[0].get("openInterest", 0))

        r = await client.get(priceUrl, timeout=8)
        if r.status_code != 200:
            return None
        priceData = r.json()
        tickers   = priceData.get("result", {}).get("list", [])
        if not tickers:
            return None
        markPx = float(tickers[0].get("markPrice", 0))

        if markPx == 0:
            return None
        return oiCoins * markPx, markPx

    except Exception as e:
        print(f"[Bybit {coin}] {e}")
        return None


async def fetchOkxOi(client, coin):
    instId   = f"{coin}-USDT-SWAP"
    oiUrl    = f"https://www.okx.com/api/v5/public/open-interest?instId={instId}"
    priceUrl = f"https://www.okx.com/api/v5/public/mark-price?instId={instId}"
    try:
        r = await client.get(oiUrl, timeout=8)
        if r.status_code != 200:
            return None
        data  = r.json()
        items = data.get("data", [])
        if not items:
            return None
        oiUsd = float(items[0].get("oiUsd", 0))

        r = await client.get(priceUrl, timeout=8)
        if r.status_code != 200:
            return None
        priceData  = r.json()
        priceItems = priceData.get("data", [])
        if not priceItems:
            return None
        markPx = float(priceItems[0].get("markPx", 0))

        return oiUsd, markPx

    except Exception as e:
        print(f"[OKX {coin}] {e}")
    return None


async def fetchDeribitOi(client, coin):
    url = (
        "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
        f"?currency={coin}&kind=future"
    )
    try:
        r = await client.get(url, timeout=8)
        if r.status_code == 200:
            data    = r.json()
            results = data.get("result", [])
            if not results:
                return None

            # open_interest is already in USD — do NOT multiply by mark_price
            totalOi = sum(
                float(item.get("open_interest", 0))
                for item in results
                if item.get("open_interest")
            )

            # still need markPx for trend label — grab from perpetual
            perp = next(
                (i for i in results if f"{coin}-PERPETUAL" in i.get("instrument_name", "")),
                results[0]
            )
            markPx = float(perp.get("mark_price", 0))

            return totalOi, markPx

    except Exception as e:
        print(f"[Deribit {coin}] {e}")
    return None


async def fetchHyperliquidOi(client, coin):
    try:
        r = await client.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "metaAndAssetCtxs"},
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            meta = data[0]["universe"]
            ctxs = data[1]
            for i, asset in enumerate(meta):
                if asset["name"] == coin:
                    ctx    = ctxs[i]
                    oi     = float(ctx.get("openInterest", 0))
                    markPx = float(ctx.get("markPx", 0))
                    return oi * markPx, markPx
    except Exception as e:
        print(f"[Hyperliquid {coin}] {e}")
    return None


# ── upsert to mongo ───────────────────────────────────────────────────────────

async def upsertOi(db, exchange, coin, oiUsd, markPx):
    if oiUsd is None or markPx is None:
        print(f"[{exchange} {coin}] fetch failed, skipping")
        return

    coll = db["exchange_oi"]
    now  = datetime.now(timezone.utc)

    existing = await coll.find_one({"exchange": exchange, "coin": coin})

    if existing:
        ts30min = existing.get("timestamp_30min")
        if ts30min:
            if isinstance(ts30min, str):
                ts30min = datetime.fromisoformat(ts30min)
            elapsed = (now - ts30min).total_seconds()
        else:
            elapsed = 9999

        if elapsed >= 1800:
            oi30minAgo = existing.get("oi_usd", oiUsd)
            px30minAgo = existing.get("mark_px", markPx)
            ts30minNew = now
        else:
            oi30minAgo = existing.get("oi_30min_ago", existing.get("oi_usd", oiUsd))
            px30minAgo = existing.get("px_30min_ago", existing.get("mark_px", markPx))
            ts30minNew = ts30min if ts30min else now
    else:
        oi30minAgo = oiUsd
        px30minAgo = markPx
        ts30minNew = now

    changePct30min = ((oiUsd - oi30minAgo) / oi30minAgo * 100) if oi30minAgo > 0 else 0
    pxChange30min  = ((markPx - px30minAgo) / px30minAgo * 100) if px30minAgo > 0 else 0
    trendLabel     = getTrendLabel(changePct30min, pxChange30min)

    if abs(changePct30min) >= SPIKE_THRESHOLD:
        print(
            f"[SPIKE] {exchange} {coin}: "
            f"${oi30minAgo/1e9:.2f}B -> ${oiUsd/1e9:.2f}B "
            f"({changePct30min:+.1f}% over 30min) | {trendLabel}"
        )

    await coll.update_one(
        {"exchange": exchange, "coin": coin},
        {
            "$set": {
                "exchange":          exchange,
                "coin":              coin,
                "oi_usd":            oiUsd,
                "mark_px":           markPx,
                "oi_30min_ago":      oi30minAgo,
                "px_30min_ago":      px30minAgo,
                "change_pct_30min":  round(changePct30min, 2),
                "px_change_30min":   round(pxChange30min, 2),
                "trend_label":       trendLabel,
                "timestamp_30min":   ts30minNew.isoformat(),
                "timestamp":         now.isoformat(),
            }
        },
        upsert=True
    )

    print(
        f"[{exchange}] {coin}: "
        f"${oiUsd/1e9:.3f}B | OI {changePct30min:+.1f}% | "
        f"PX {pxChange30min:+.1f}% | {trendLabel}"
    )


# ── main loop ─────────────────────────────────────────────────────────────────

async def main():
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client["hyperliquid"]

    await db["exchange_oi"].create_index(
        [("exchange", 1), ("coin", 1)],
        unique=True
    )

    while True:
        print(f"\nFetching exchange OI at {datetime.now(timezone.utc).isoformat()}")
        print("-" * 60)

        async with httpx.AsyncClient() as client:
            for coin in TARGET_COINS:
                results = await asyncio.gather(
                    fetchBinanceOi(client,     coin),
                    fetchBybitOi(client,       coin),
                    fetchOkxOi(client,         coin),
                    fetchDeribitOi(client,     coin),
                    fetchHyperliquidOi(client, coin),
                )

                exchanges = ["Binance", "Bybit", "OKX", "Deribit", "Hyperliquid"]
                for exchange, result in zip(exchanges, results):
                    if result is None:
                        await upsertOi(db, exchange, coin, None, None)
                    else:
                        oiUsd, markPx = result
                        await upsertOi(db, exchange, coin, oiUsd, markPx)

        print("-" * 60)
        print("Next update in 5 minutes")
        await asyncio.sleep(5 * 60)


if __name__ == "__main__":
    asyncio.run(main())
