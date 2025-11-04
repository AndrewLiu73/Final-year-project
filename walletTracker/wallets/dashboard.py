import streamlit as st
import asyncio
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient
from collections import Counter
import pandas as pd
import os
import datetime


def format_time():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# Set your env vars via Render dashboard, or .env locally
MONGO_URI = os.getenv("MONGO_URI")
API_URL = os.getenv("API_URL")
DB_NAME, COLL = "hyperliquid", "millionaires"
COINS = ["BTC", "ETH", "HYPE"]
RETRY, PARALLEL = 3, 10


async def fetch_wallets():
    cli = AsyncIOMotorClient(MONGO_URI)
    docs = await cli[DB_NAME][COLL].find({}, {"_id": 0, "wallet": 1}).to_list(None)
    return [d["wallet"] for d in docs if "wallet" in d]


async def fetch_position(session, wallet):
    for attempt in range(RETRY):
        try:
            async with session.post(API_URL, json={"type": "clearinghouseState", "user": wallet}) as resp:
                if resp.status == 200:
                    js = await resp.json()
                    return wallet, js.get("assetPositions", [])
        except Exception:
            pass
        await asyncio.sleep(2 ** attempt)
    return wallet, []


async def process_wallets(wallets):
    wallet_bias = {}
    agg_val = {c: Counter() for c in COINS}
    async with aiohttp.ClientSession() as session:
        sema = asyncio.Semaphore(PARALLEL)

        async def worker(wallet):
            async with sema:
                w, positions = await fetch_position(session, wallet)
                per_val = {c: Counter() for c in COINS}
                for pos in positions:
                    coin = pos.get("position", {}).get("coin")
                    szi = float(pos.get("position", {}).get("szi", 0))
                    val = float(pos.get("position", {}).get("positionValue", 0))
                    if coin in COINS and szi and val:
                        side = "B" if szi > 0 else "A"
                        agg_val[coin][side] += val
                        per_val[coin][side] += val
                wallet_bias[wallet] = {}
                for coin in COINS:
                    long_val = per_val[coin].get("B", 0.0)
                    short_val = per_val[coin].get("A", 0.0)
                    total = long_val + short_val
                    l_pct = (long_val / total * 100) if total else 0
                    s_pct = (short_val / total * 100) if total else 0
                    direction = "Long" if long_val > short_val else "Short" if short_val > long_val else "Neutral"
                    wallet_bias[wallet][coin] = {
                        "long": long_val, "short": short_val,
                        "long_pct": l_pct, "short_pct": s_pct,
                        "direction": direction
                    }

        await asyncio.gather(*[worker(w) for w in wallets])
    agg_bias = {}
    for coin in COINS:
        long_val = agg_val[coin]["B"]
        short_val = agg_val[coin]["A"]
        total = long_val + short_val
        l_pct = (long_val / total * 100) if total else 0
        s_pct = (short_val / total * 100) if total else 0
        dirn = "Long" if long_val > short_val else "Short" if short_val > long_val else "Neutral"
        agg_bias[coin] = {
            "long": long_val, "short": short_val,
            "long_pct": l_pct, "short_pct": s_pct,
            "direction": dirn
        }
    return wallet_bias, agg_bias


st.set_page_config(page_title="Millionaire Bias Tracker", layout="wide")
st.title("Millionaire Bias Tracker")

btn = st.button("Refresh Bias Now")
if btn:
    with st.spinner("Updating wallets and positions, please wait..."):
        wallets = asyncio.run(fetch_wallets())
        if wallets:
            wallet_bias, agg_bias = asyncio.run(process_wallets(wallets))
            st.success(f"Updated at {format_time()}! {len(wallets)} wallets loaded.")

            # Aggregate bias table
            agg_records = []
            for coin, stats in agg_bias.items():
                agg_records.append({
                    "Coin": coin,
                    "Direction": stats["direction"],
                    "Long": stats["long"],
                    "Long %": stats["long_pct"],
                    "Short": stats["short"],
                    "Short %": stats["short_pct"]
                })
            agg_df = pd.DataFrame(agg_records)
            st.header("Aggregate Bias")
            st.dataframe(agg_df)

            # Individual bias table
            ind_records = []
            for wallet, coins in wallet_bias.items():
                for coin, s in coins.items():
                    ind_records.append({
                        "Wallet": wallet,
                        "Coin": coin,
                        "Direction": s["direction"],
                        "Long": s["long"],
                        "Long %": s["long_pct"],
                        "Short": s["short"],
                        "Short %": s["short_pct"]
                    })
            ind_df = pd.DataFrame(ind_records)
            st.header("Individual Wallet Bias")
            # Optionally: Let user filter by wallet below
            wallets_list = sorted({row['Wallet'] for row in ind_records})
            selection = st.multiselect("Select wallets to display", wallets_list, default=wallets_list[:5])
            filtered_df = ind_df[ind_df['Wallet'].isin(selection)]
            st.dataframe(filtered_df)
        else:
            st.error("No wallets found or MongoDB error!")
else:
    st.info("Click 'Refresh Bias Now' to load stats.")