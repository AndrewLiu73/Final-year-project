import aiohttp
import asyncio
from pathlib import Path
import random

HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"
GOOD_TRADERS_FILE = "data/goodTraders.txt"
POSITIONS_OUTPUT_FILE = "positions_output.txt"
RATE_LIMIT_DELAY = 1.5
MAX_RETRIES = 3

def load_wallets():
    path = Path(GOOD_TRADERS_FILE)
    if not path.exists():
        raise FileNotFoundError(f"{GOOD_TRADERS_FILE} not found")
    with path.open() as f:
        return [line.strip() for line in f if line.strip().startswith("0x") and len(line.strip()) == 42]

async def fetch_open_positions(session, wallet):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                HYPERLIQUID_API,
                json={"type": "clearinghouseState", "user": wallet}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("assetPositions", [])
                elif resp.status == 429:
                    print(f"[{wallet}] Rate limited. Retrying...")
                    await asyncio.sleep(2 ** attempt)
                else:
                    print(f"[{wallet}] Error: {resp.status}")
                    return []
        except Exception as e:
            print(f"[{wallet}] Exception: {e}")
            return []
    print(f"[{wallet}] Failed after {MAX_RETRIES} retries")
    return []

async def write_positions_to_file(session, wallets):
    lines = []
    for wallet in wallets:
        positions = await fetch_open_positions(session, wallet)
        for item in positions:
            pos = item.get("position", {})
            coin = pos.get("coin")
            szi = float(pos.get("szi", 0))
            entry = float(pos.get("entryPx", 0))
            if szi == 0:
                continue
            side = "Long" if szi > 0 else "Short"
            lines.append(f"{wallet},{coin},{side},{entry:.2f},{abs(szi):.4f}")
        await asyncio.sleep(RATE_LIMIT_DELAY + random.uniform(0.1, 0.3))

    with open(POSITIONS_OUTPUT_FILE, "w") as f:
        f.write("wallet,coin,side,entryPx,szi\n")
        for line in lines:
            f.write(f"{line}\n")

async def main():
    wallets = load_wallets()
    async with aiohttp.ClientSession() as session:
        await write_positions_to_file(session, wallets)

if __name__ == "__main__":
    asyncio.run(main())
