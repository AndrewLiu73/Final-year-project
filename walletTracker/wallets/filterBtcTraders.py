import asyncio
import aiohttp
from pathlib import Path
from hyperliquid.utils import constants

API_URL = f"{constants.MAINNET_API_URL}/info"
INPUT_FILE = Path("allUsers.txt")
OUTPUT_FILE = Path("filteredUsers.txt")

async def fetch_btc_fills(session, wallet):
    payload = {"type": "userFills", "user": wallet, "startTime": 0}
    async with session.post(API_URL, json=payload) as resp:
        resp.raise_for_status()
        fills = await resp.json()
    return [f for f in fills if 'BTC' in f.get('coin', '').upper()]

async def fetch_account_value(session, wallet):
    payload = {"type": "clearinghouseState", "user": wallet}
    async with session.post(API_URL, json=payload) as resp:
        if resp.status != 200:
            return 0.0
        data = await resp.json()
        return float(data.get("marginSummary", {}).get("accountValue", 0.0))

async def evaluate_wallet(session, wallet):
    fills = await fetch_btc_fills(session, wallet)
    total_trades = len(fills)
    pnl = 0.0
    for f in fills:
        if "closedPnl" in f:
            pnl += float(f["closedPnl"])
    account_value = await fetch_account_value(session, wallet)
    return total_trades, pnl, account_value


async def filter_users():
    wallets = [line.strip() for line in INPUT_FILE.read_text().splitlines() if line.strip().startswith("0x")]
    qualified = []

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        for wallet in wallets:
            try:
                trades, pnl, acct_value = await evaluate_wallet(session, wallet)
                if trades >= 50 and pnl >= 1000 and acct_value >= 10000:
                    qualified.append(wallet)
                    print(f"[✓] {wallet} passed: Trades={trades}, PnL=${pnl:.2f}, Account=${acct_value:.2f}")
                else:
                    print(f"[x] {wallet} failed: Trades={trades}, PnL=${pnl:.2f}, Account=${acct_value:.2f}")
            except Exception as e:
                print(f"[!] Error evaluating {wallet}: {e}")
            await asyncio.sleep(0.1)  # rate limiting

    OUTPUT_FILE.write_text("\n".join(qualified))
    print(f"\n✅ Done. {len(qualified)} wallets written to {OUTPUT_FILE.name}")

if __name__ == "__main__":
    asyncio.run(filter_users())
