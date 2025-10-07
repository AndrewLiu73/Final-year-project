import aiohttp
import asyncio
import json
import random
from pathlib import Path
from collections import defaultdict

HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"
GOOD_TRADERS_FILE = "data/goodTraders.txt"
ORDERS_OUTPUT_FILE = "orders_output.txt"
CHECK_INTERVAL = 30  # seconds
RATE_LIMIT_DELAY = 1.5  # seconds between each wallet to avoid 429s
MAX_RETRIES = 3

def load_wallets():
    path = Path(GOOD_TRADERS_FILE)
    if not path.exists():
        raise FileNotFoundError(f"{GOOD_TRADERS_FILE} not found")
    with path.open() as f:
        return [line.strip() for line in f if line.strip().startswith("0x") and len(line.strip()) == 42]

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

def merge_orders_by_wallet_coin_side(orders):
    merged = defaultdict(float)
    for order in orders:
        wallet = order['wallet']
        coin = order['coin']
        side = order['side']
        px = float(order['px'])
        sz = float(order.get('sz', 1))  # Optional: default to 1 if 'sz' is missing
        key = (wallet, coin, side, px)
        merged[key] += sz

    final_orders = []
    for (wallet, coin, side, px), total_sz in merged.items():
        final_orders.append({
            'wallet': wallet,
            'coin': coin,
            'side': side,
            'px': f"{px:.2f}",
            'sz': f"{total_sz:.4f}"
        })
    return final_orders


async def write_orders_to_file(session, wallets):
    raw_lines = []
    for wallet in wallets:
        orders = await fetch_open_orders(session, wallet)
        for order in orders:
            px_raw = order.get("px") or order.get("limitPx")
            if px_raw is None:
                print(f"[SKIPPED] Missing px in order: {order}")
                continue
            try:
                px = float(px_raw)
                sz = float(order.get("sz", 0))
            except ValueError:
                print(f"[SKIPPED] Invalid px or sz in order: {order}")
                continue
            raw_lines.append({
                'wallet': wallet,
                'coin': order.get("coin"),
                'side': order.get("side"),
                'px': px,
                'sz': float(order.get("sz", 0))
            })

        await asyncio.sleep(RATE_LIMIT_DELAY + random.uniform(0.1, 0.3))

    # Merge duplicates
    merged_lines = merge_orders_by_wallet_coin_side(raw_lines)

    with open(ORDERS_OUTPUT_FILE, "w") as f:
        f.write("wallet,coin,side,px,sz\n")
        for order in merged_lines:
            f.write(f"{order['wallet']},{order['coin']},{order['side']},{order['px']},{order['sz']}\n")

async def main():
    wallets = load_wallets()
    async with aiohttp.ClientSession() as session:
        await write_orders_to_file(session, wallets)

if __name__ == "__main__":
    asyncio.run(main())
