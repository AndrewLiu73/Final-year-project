"""
singleScan.py - scan a single wallet and print the results
useful for debugging or checking a specific trader without running the full scanner
"""

import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

sys.path.append(str(Path(__file__).resolve().parent))
from profitabilityScanner import ProfitabilityScanner

MONGO_URI = os.getenv("MONGO_URI")


async def scanWallet(walletAddress: str, saveToMongo: bool = True):
    print(f"Scanning wallet: {walletAddress}")
    print(f"Started at:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    scanner = ProfitabilityScanner(MONGO_URI, rpm=200)

    # calculate_profitability is async now because it uses httpx under the hood
    # instead of blocking requests. need to await it and clean up the session after
    try:
        metrics = await scanner.calculate_profitability(walletAddress)
    finally:
        await scanner.close()

    if metrics == "bot":
        print(f"\nWallet flagged as bot — minimal record saved to profitability_metrics.")
        print(f"Done at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return "bot"

    if not metrics:
        print("No metrics returned — wallet may be invalid or API failed.")
        return None

    print("\nResults:")
    print("-" * 60)
    for key, value in metrics.items():
        if isinstance(value, list) and len(value) > 5:
            print(f"  {key}: [{len(value)} items — truncated]")
        elif isinstance(value, dict) and key in ("historical_pnl", "historical_balance"):
            for period, points in value.items():
                print(f"  {key}.{period}: [{len(points)} data points]")
        else:
            print(f"  {key}: {value}")

    print("-" * 60)
    print(f"\nSummary:")
    print(f"  Has activity:   {metrics.get('has_trading_activity')}")
    print(f"  Account value:  ${metrics.get('account_value', 0):,.2f}")
    print(f"  Total PnL:      ${metrics.get('total_pnl_usdc', 0):,.2f}")
    print(f"  Win rate:       {metrics.get('win_rate_percentage', 0):.1f}%")
    print(f"  Trade count:    {metrics.get('trade_count', 0):,}")
    print(f"  Max drawdown:   {metrics.get('max_drawdown_percentage', 0):.1f}%")
    print(f"  Is bot:         {metrics.get('is_likely_bot')}")
    print(f"  Role:           {metrics.get('user_role')}")
    print(f"  Fee tier:       {metrics.get('fee_tier')}")
    print(f"  Open positions: {metrics.get('open_positions_count', 0)}")

    if metrics.get("open_positions"):
        print("\n  Open positions:")
        for pos in metrics["open_positions"]:
            print(
                f"    {pos['asset']} {pos['direction']} "
                f"size={pos['size']} "
                f"entry={pos['entry_price']} "
                f"uPnL=${pos['unrealized_pnl']}"
            )

    if not saveToMongo:
        print("\nMongo save skipped (--dry-run mode)")
        return metrics

    # save to mongo asynchronously using motor
    client = AsyncIOMotorClient(MONGO_URI)
    db = client["hyperliquid"]
    result = await db.profitability_metrics.update_one(
        {"wallet_address": walletAddress},
        {"$set": metrics},
        upsert=True
    )
    client.close()

    if result.upserted_id:
        print(f"\nInserted new document into profitability_metrics")
    else:
        print(f"\nUpdated existing document in profitability_metrics")

    print(f"Done at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return metrics


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python singleScan.py <wallet_address> [--dry-run]")
        print("Example:")
        print("  python singleScan.py 0x6ba2ad09aa6629a423b59b71f3564d84ce66c001")
        print("  python singleScan.py 0x6ba2ad09aa6629a423b59b71f3564d84ce66c001 --dry-run")
        sys.exit(1)

    wallet = sys.argv[1]
    dryRun = "--dry-run" in sys.argv

    # asyncio.run() creates an event loop and runs the coroutine.
    # needed because the scanner uses async httpx calls now
    asyncio.run(scanWallet(wallet, saveToMongo=not dryRun))
