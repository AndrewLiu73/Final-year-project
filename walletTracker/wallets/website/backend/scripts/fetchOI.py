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

def get_trend_label(oi_chg: float, px_chg: float) -> str:
    oi_up   = oi_chg >  3.0
    oi_down = oi_chg < -3.0
    px_up   = px_chg >  1.0
    px_down = px_chg < -1.0

    if oi_up and px_up:
        return "Building Long"
    if oi_up and px_down:
        return "Squeeze Risk"
    if oi_up and not px_up and not px_down:
        return "Crowded / Fragile"
    if oi_down and px_up:
        return "Short Covering"
    if oi_down and px_down:
        return "Deleveraging"
    return "Neutral"


# ── fetchers — all return (oi_usd, mark_px) or None ──────────────────────────

async def fetch_binance_oi(client, coin):
    symbol = f"{coin}USDT"
    url    = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
    try:
        r = await client.get(url, timeout=8)
        if r.status_code == 200:
            data     = r.json()
            oi_coins = float(data.get("openInterest", 0))
            price_url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
            pr = await client.get(price_url, timeout=8)
            price_data = pr.json() if pr.status_code == 200 else {}
            mark_px = float(price_data.get("markPrice", 0))
            return oi_coins * mark_px, mark_px
    except Exception as e:
        print(f"[Binance {coin}] {e}")
    return None


async def fetch_bybit_oi(client, coin):
    symbol    = f"{coin}USDT"
    oi_url    = (
        "https://api.bybit.com/v5/market/open-interest"
        f"?category=linear&symbol={symbol}&intervalTime=5min&limit=1"
    )
    price_url = (
        "https://api.bybit.com/v5/market/tickers"
        f"?category=linear&symbol={symbol}"
    )
    try:
        r = await client.get(oi_url, timeout=8)
        if r.status_code != 200:
            return None
        oi_data = r.json()
        if oi_data.get("retCode", -1) != 0:
            return None
        items = oi_data.get("result", {}).get("list", [])
        if not items:
            return None
        oi_coins = float(items[0].get("openInterest", 0))

        r = await client.get(price_url, timeout=8)
        if r.status_code != 200:
            return None
        price_data = r.json()
        tickers    = price_data.get("result", {}).get("list", [])
        if not tickers:
            return None
        mark_px = float(tickers[0].get("markPrice", 0))

        if mark_px == 0:
            return None
        return oi_coins * mark_px, mark_px

    except Exception as e:
        print(f"[Bybit {coin}] {e}")
        return None


async def fetch_okx_oi(client, coin):
    inst_id   = f"{coin}-USDT-SWAP"
    oi_url    = f"https://www.okx.com/api/v5/public/open-interest?instId={inst_id}"
    price_url = f"https://www.okx.com/api/v5/public/mark-price?instId={inst_id}"
    try:
        r = await client.get(oi_url, timeout=8)
        if r.status_code != 200:
            return None
        data  = r.json()
        items = data.get("data", [])
        if not items:
            return None
        oi_usd = float(items[0].get("oiUsd", 0))

        r = await client.get(price_url, timeout=8)
        if r.status_code != 200:
            return None
        price_data  = r.json()
        price_items = price_data.get("data", [])
        if not price_items:
            return None
        mark_px = float(price_items[0].get("markPx", 0))

        return oi_usd, mark_px

    except Exception as e:
        print(f"[OKX {coin}] {e}")
    return None


async def fetch_deribit_oi(client, coin):
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
            total_oi = sum(
                float(item.get("open_interest", 0))
                for item in results
                if item.get("open_interest")
            )

            # still need mark_px for trend label — grab from perpetual
            perp = next(
                (i for i in results if f"{coin}-PERPETUAL" in i.get("instrument_name", "")),
                results[0]
            )
            mark_px = float(perp.get("mark_price", 0))

            return total_oi, mark_px

    except Exception as e:
        print(f"[Deribit {coin}] {e}")
    return None


async def fetch_hyperliquid_oi(client, coin):
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
                    ctx     = ctxs[i]
                    oi      = float(ctx.get("openInterest", 0))
                    mark_px = float(ctx.get("markPx", 0))
                    return oi * mark_px, mark_px
    except Exception as e:
        print(f"[Hyperliquid {coin}] {e}")
    return None


# ── upsert to mongo ───────────────────────────────────────────────────────────

async def upsert_oi(db, exchange, coin, oi_usd, mark_px):
    if oi_usd is None or mark_px is None:
        print(f"[{exchange} {coin}] fetch failed, skipping")
        return

    coll = db["exchange_oi"]
    now  = datetime.now(timezone.utc)

    existing = await coll.find_one({"exchange": exchange, "coin": coin})

    if existing:
        ts_30min = existing.get("timestamp_30min")
        if ts_30min:
            if isinstance(ts_30min, str):
                ts_30min = datetime.fromisoformat(ts_30min)
            elapsed = (now - ts_30min).total_seconds()
        else:
            elapsed = 9999

        if elapsed >= 1800:
            oi_30min_ago = existing.get("oi_usd", oi_usd)
            px_30min_ago = existing.get("mark_px", mark_px)
            ts_30min_new = now
        else:
            oi_30min_ago = existing.get("oi_30min_ago", existing.get("oi_usd", oi_usd))
            px_30min_ago = existing.get("px_30min_ago", existing.get("mark_px", mark_px))
            ts_30min_new = ts_30min if ts_30min else now
    else:
        oi_30min_ago = oi_usd
        px_30min_ago = mark_px
        ts_30min_new = now

    change_pct_30min = ((oi_usd - oi_30min_ago) / oi_30min_ago * 100) if oi_30min_ago > 0 else 0
    px_change_30min  = ((mark_px - px_30min_ago) / px_30min_ago * 100) if px_30min_ago > 0 else 0
    trend_label      = get_trend_label(change_pct_30min, px_change_30min)

    if abs(change_pct_30min) >= SPIKE_THRESHOLD:
        print(
            f"[SPIKE] {exchange} {coin}: "
            f"${oi_30min_ago/1e9:.2f}B -> ${oi_usd/1e9:.2f}B "
            f"({change_pct_30min:+.1f}% over 30min) | {trend_label}"
        )

    await coll.update_one(
        {"exchange": exchange, "coin": coin},
        {
            "$set": {
                "exchange":          exchange,
                "coin":              coin,
                "oi_usd":            oi_usd,
                "mark_px":           mark_px,
                "oi_30min_ago":      oi_30min_ago,
                "px_30min_ago":      px_30min_ago,
                "change_pct_30min":  round(change_pct_30min, 2),
                "px_change_30min":   round(px_change_30min, 2),
                "trend_label":       trend_label,
                "timestamp_30min":   ts_30min_new.isoformat(),
                "timestamp":         now.isoformat(),
            }
        },
        upsert=True
    )

    print(
        f"[{exchange}] {coin}: "
        f"${oi_usd/1e9:.3f}B | OI {change_pct_30min:+.1f}% | "
        f"PX {px_change_30min:+.1f}% | {trend_label}"
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
                    fetch_binance_oi(client,     coin),
                    fetch_bybit_oi(client,       coin),
                    fetch_okx_oi(client,         coin),
                    fetch_deribit_oi(client,     coin),
                    fetch_hyperliquid_oi(client, coin),
                )

                exchanges = ["Binance", "Bybit", "OKX", "Deribit", "Hyperliquid"]
                for exchange, result in zip(exchanges, results):
                    if result is None:
                        await upsert_oi(db, exchange, coin, None, None)
                    else:
                        oi_usd, mark_px = result
                        await upsert_oi(db, exchange, coin, oi_usd, mark_px)

        print("-" * 60)
        print("Next update in 5 minutes")
        await asyncio.sleep(5 * 60)


if __name__ == "__main__":
    asyncio.run(main())
