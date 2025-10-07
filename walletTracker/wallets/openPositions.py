import aiohttp
import asyncio
from pathlib import Path
from collections import Counter, defaultdict

HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"
GOOD_TRADERS_FILE = "goodTraders.txt"
RATE_LIMIT_DELAY = 1.5  # seconds between wallet requests
LOOP_DELAY = 60  # delay between summary refreshes
TARGET_COINS = ["BTC", "HYPE"]
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
                elif resp.status == 422:
                    print(f"[{wallet}] ❌ Wallet not supported or invalid (422)")
                    return []
                else:
                    print(f"[{wallet}] Error: {resp.status}")
        except Exception as e:
            print(f"[{wallet}] Exception: {e}")

        wait_time = 2 ** attempt
        print(f"[{wallet}] Retry {attempt + 1}/{MAX_RETRIES} in {wait_time}s...")
        await asyncio.sleep(wait_time)

    print(f"[{wallet}] ⚠️ Failed after {MAX_RETRIES} attempts.")
    return []


async def process_wallets(session, wallets):
    total_bias_qty = {coin: Counter() for coin in TARGET_COINS}
    total_bias_val = {coin: Counter() for coin in TARGET_COINS}

    for wallet in wallets:
        try:
            positions = await fetch_positions(session, wallet)
            if not positions:
                continue

            print(f"\n[{wallet}] Open Positions:")
            for pos_data in positions:
                pos = pos_data.get("position", {})
                coin = pos.get("coin")
                szi = float(pos.get("szi", 0))
                val = float(pos.get("positionValue", 0))
                if szi == 0 or val == 0:
                    continue

                direction = "Long" if szi > 0 else "Short"
                print(f"    {coin} → {direction} {abs(szi):.4f} | ${val:.2f} USDC")

                if coin in total_bias_qty:
                    side = "B" if szi > 0 else "A"
                    total_bias_qty[coin][side] += abs(szi)
                    total_bias_val[coin][side] += val

            await asyncio.sleep(RATE_LIMIT_DELAY)
        except Exception as e:
            print(f"[{wallet}] Unexpected error: {e}")

    return total_bias_qty, total_bias_val


async def print_bias_summary(total_bias_qty, total_bias_val):
    print("\n===== Directional Bias Summary =====")
    for coin in TARGET_COINS:
        # Raw size
        long_sz = total_bias_qty[coin].get("B", 0.0)
        short_sz = total_bias_qty[coin].get("A", 0.0)
        total_sz = long_sz + short_sz

        # USD notional
        long_val = total_bias_val[coin].get("B", 0.0)
        short_val = total_bias_val[coin].get("A", 0.0)
        total_val = long_val + short_val

        long_pct = (long_val / total_val * 100) if total_val > 0 else 0
        short_pct = (short_val / total_val * 100) if total_val > 0 else 0
        direction = "Long" if long_val > short_val else "Short" if short_val > long_val else "Neutral"

        print(f"{coin} Bias → {direction}")
        print(f"    Size     → Long: {long_sz:.4f} | Short: {short_sz:.4f}")
        print(f"    Position → Long: ${long_val:.2f} ({long_pct:.1f}%) | Short: ${short_val:.2f} ({short_pct:.1f}%)")
    print("=====================================\n")


async def main():
    wallets = load_wallets()
    print(f"Loaded {len(wallets)} wallets.")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                qty_bias, val_bias = await process_wallets(session, wallets)
                await print_bias_summary(qty_bias, val_bias)
            except Exception as e:
                print(f"🔴 Critical loop error: {e}")
            print(f"⏳ Waiting {LOOP_DELAY}s before next round...\n")
            await asyncio.sleep(LOOP_DELAY)


if __name__ == "__main__":
    asyncio.run(main())