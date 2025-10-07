import aiohttp
import asyncio
import json
import random
from pathlib import Path
from collections import defaultdict, Counter

HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"
GOOD_TRADERS_FILE = "data/goodTraders.txt"
CHECK_INTERVAL = 30  # seconds
RATE_LIMIT_DELAY = 1.5  # seconds between each wallet to avoid 429s
MAX_RETRIES = 3

async def fetch_open_orders(session, wallet):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                HYPERLIQUID_API,
                json={"type": "openOrders", "user": wallet}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 429:
                    print(f"[{wallet}] HTTP 429 – rate limited. Retrying...")
                    await asyncio.sleep(2 ** attempt)
                else:
                    print(f"[{wallet}] Error: {resp.status}")
                    return []
        except Exception as e:
            print(f"[{wallet}] Exception: {e}")
            return []
    print(f"[{wallet}] Failed after {MAX_RETRIES} retries")
    return []

def aggregate_orders(orders):
    aggregated = defaultdict(lambda: defaultdict(float))
    for order in orders:
        coin = order["coin"]
        side = order["side"]
        sz = float(order["sz"])
        aggregated[coin][side] += sz
    return aggregated

def extract_bias_by_coin(orders, coin_symbol):
    bias = Counter()
    for order in orders:
        if order["coin"] == coin_symbol:
            side = order["side"]
            bias[side] += float(order["sz"])
    return bias

async def monitor_wallets(wallets):
    print(f"Tracking {len(wallets)} wallets…")
    previous_orders = defaultdict(list)
    total_btc_bias = Counter()
    total_hype_bias = Counter()

    async with aiohttp.ClientSession() as session:
        while True:
            total_btc_bias.clear()
            total_hype_bias.clear()

            for wallet in wallets:
                orders = await fetch_open_orders(session, wallet)

                btc_bias = extract_bias_by_coin(orders, "BTC")
                hype_bias = extract_bias_by_coin(orders, "HYPE")

                total_btc_bias.update(btc_bias)
                total_hype_bias.update(hype_bias)

                # Check for updates to wallet's open orders
                prev_set = {(o['oid'], o['sz']) for o in previous_orders[wallet]}
                curr_set = {(o['oid'], o['sz']) for o in orders}
                if prev_set != curr_set:
                    print(f"[{wallet}] 🆕 Open orders updated")
                    aggregated = aggregate_orders(orders)
                    for coin, sides in aggregated.items():
                        long_sz = sides.get('B', 0.0)
                        short_sz = sides.get('A', 0.0)
                        print(f"    {coin} Total → Long: {long_sz:.2f} | Short: {short_sz:.2f}")
                    previous_orders[wallet] = orders

                await asyncio.sleep(RATE_LIMIT_DELAY + random.uniform(0.1, 0.5))

            print("\n===== Directional Bias Summary =====")
            btc_long = total_btc_bias.get('B', 0.0)
            btc_short = total_btc_bias.get('A', 0.0)
            hype_long = total_hype_bias.get('B', 0.0)
            hype_short = total_hype_bias.get('A', 0.0)

            btc_total = btc_long + btc_short
            hype_total = hype_long + hype_short

            btc_long_pct = (btc_long / btc_total * 100) if btc_total > 0 else 0
            btc_short_pct = (btc_short / btc_total * 100) if btc_total > 0 else 0

            hype_long_pct = (hype_long / hype_total * 100) if hype_total > 0 else 0
            hype_short_pct = (hype_short / hype_total * 100) if hype_total > 0 else 0

            btc_bias_direction = "Long" if btc_long > btc_short else "Short" if btc_short > btc_long else "Neutral"
            hype_bias_direction = "Long" if hype_long > hype_short else "Short" if hype_short > hype_long else "Neutral"

            print(f"BTC Bias → {btc_bias_direction} | Long: {btc_long:.2f} ({btc_long_pct:.1f}%) | Short: {btc_short:.2f} ({btc_short_pct:.1f}%)")
            print(f"HYPE Bias → {hype_bias_direction} | Long: {hype_long:.2f} ({hype_long_pct:.1f}%) | Short: {hype_short:.2f} ({hype_short_pct:.1f}%)")
            print("===================================\n")

            await asyncio.sleep(CHECK_INTERVAL)

def load_wallets():
    path = Path(GOOD_TRADERS_FILE)
    if not path.exists():
        raise FileNotFoundError(f"{GOOD_TRADERS_FILE} not found")

    with path.open() as f:
        return [line.strip() for line in f if line.strip() and line.strip().startswith("0x")]

if __name__ == "__main__":
    wallets = load_wallets()
    asyncio.run(monitor_wallets(wallets))
