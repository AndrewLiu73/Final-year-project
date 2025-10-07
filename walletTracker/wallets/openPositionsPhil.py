import aiohttp
import asyncio
from pathlib import Path
from collections import Counter
from datetime import datetime

# --- Config
HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"
GOOD_TRADERS_FILE = "data/goodTraders.txt"
OUTPUT_FILE = "data/bias_summary.txt"
RATE_LIMIT_DELAY = 1.5
LOOP_DELAY = 30  # One update per minute
TARGET_COINS = ["BTC", "HYPE", "ETH"]
MAX_RETRIES = 3

def load_wallets():
    path = Path(GOOD_TRADERS_FILE)
    if not path.exists():
        raise FileNotFoundError(f"{GOOD_TRADERS_FILE} not found")
    with path.open() as f:
        return [line.strip() for line in f if line.strip().startswith("0x") and len(line.strip()) == 42]

async def fetch_positions(session, wallet):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                HYPERLIQUID_API,
                json={"type": "clearinghouseState", "user": wallet}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("assetPositions", [])
        except:
            await asyncio.sleep(2 ** attempt)
    return []

async def process_wallets(session, wallets):
    total_bias_qty = {coin: Counter() for coin in TARGET_COINS}
    total_bias_val = {coin: Counter() for coin in TARGET_COINS}
    unique_wallets = {coin: {"B": set(), "A": set()} for coin in TARGET_COINS}

    for wallet in wallets:
        positions = await fetch_positions(session, wallet)
        for pos_data in positions:
            pos = pos_data.get("position", {})
            coin = pos.get("coin")
            szi = float(pos.get("szi", 0))
            val = float(pos.get("positionValue", 0))
            if szi == 0 or val == 0 or coin not in TARGET_COINS:
                continue

            side = "B" if szi > 0 else "A"
            total_bias_qty[coin][side] += abs(szi)
            total_bias_val[coin][side] += val
            unique_wallets[coin][side].add(wallet)

        await asyncio.sleep(RATE_LIMIT_DELAY)

    return total_bias_qty, total_bias_val, unique_wallets

async def print_and_save_summary(total_bias_qty, total_bias_val, unique_wallets):
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    summary_parts = [f"{timestamp}"]

    for coin in TARGET_COINS:
        long_sz = total_bias_qty[coin].get("B", 0.0)
        short_sz = total_bias_qty[coin].get("A", 0.0)
        long_val = total_bias_val[coin].get("B", 0.0)
        short_val = total_bias_val[coin].get("A", 0.0)
        long_wallets = len(unique_wallets[coin]["B"])
        short_wallets = len(unique_wallets[coin]["A"])

        total_val = long_val + short_val
        long_pct = (long_val / total_val * 100) if total_val > 0 else 0
        short_pct = (short_val / total_val * 100) if total_val > 0 else 0

        direction = "Long" if long_val > short_val else "Short" if short_val > long_val else "Neutral"

        part = (
            f"{coin}: {direction} | %Long: {long_pct:.1f}% | %Short: {short_pct:.1f}% | "
            f"Wallets Long: {long_wallets} | Wallets Short: {short_wallets} | "
            f"$Vol Long: {long_val:.2f} | $Vol Short: {short_val:.2f}"
        )
        summary_parts.append(part)

    line = " || ".join(summary_parts)
    print(line)
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

async def main():
    wallets = load_wallets()
    async with aiohttp.ClientSession() as session:
        while True:
            qty_bias, val_bias, unique_wallets = await process_wallets(session, wallets)
            await print_and_save_summary(qty_bias, val_bias, unique_wallets)
            await asyncio.sleep(LOOP_DELAY)

if __name__ == "__main__":
    asyncio.run(main())
