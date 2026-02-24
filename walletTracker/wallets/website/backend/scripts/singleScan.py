"""
scanSingleWallet.py
"""

import sys
import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

sys.path.append(str(Path(__file__).resolve().parent))
from profitabilityScanner import ProfitabilityScanner


MONGO_URI = os.getenv("MONGO_URI")
DB_NAME   = "hyperliquid"


def api_post_with_backoff(payload, delay, retries=5):
    for attempt in range(retries):
        try:
            resp = requests.post(
                "https://api.hyperliquid.xyz/info",
                json=payload,
                timeout=10
            )

            if resp.status_code == 200:
                return resp.json(), delay

            if resp.status_code == 429:
                wait = 5 * (2 ** attempt)
                print(f"  [429] rate limited on {payload.get('type')} "
                      f"— backing off {wait}s (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
                delay = min(delay * 1.5, 10.0)
                print(f"  [429] delay increased to {delay:.2f}s")
                continue

            if resp.status_code == 422:
                return None, delay

            print(f"  HTTP {resp.status_code} on {payload.get('type')}")
            return None, delay

        except requests.exceptions.Timeout:
            wait = 2 * (attempt + 1)
            print(f"  timeout on {payload.get('type')} — retrying in {wait}s")
            time.sleep(wait)

        except Exception as e:
            print(f"  request error on {payload.get('type')}: {e}")
            return None, delay

    print(f"  [FAILED] {payload.get('type')} after {retries} attempts — skipping")
    return None, delay


def fetch_fills_with_backoff(wallet_address, delay):
    """
    Fetches ALL fills for a wallet with full 429 backoff.
    No page cap — will paginate until all fills are retrieved.
    """
    all_fills = []
    page      = 0

    print(f"  fetching fills for {wallet_address}...")

    data, delay = api_post_with_backoff(
        {"type": "userFills", "user": wallet_address}, delay
    )
    fills = data if data else []
    all_fills.extend(fills)
    page += 1

    while len(fills) >= 2000:
        time.sleep(delay)
        oldest_time = min(int(f['time']) for f in fills)

        print(f"  fill page {page + 1} — {len(all_fills)} fills so far")

        data, delay = api_post_with_backoff(
            {
                "type":    "userFills",
                "user":    wallet_address,
                "endTime": oldest_time - 1
            },
            delay
        )

        fills = data if data else []

        if not fills:
            print(f"  fill pagination complete at page {page + 1}")
            break

        all_fills.extend(fills)
        page += 1

    print(f"  total fills fetched: {len(all_fills)} across {page} page(s)")
    return all_fills, delay


def scan_wallet(wallet_address: str, save_to_mongo: bool = True):
    print(f"Scanning wallet: {wallet_address}")
    print(f"Started at:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    delay   = 60.0 / 200
    scanner = ProfitabilityScanner(MONGO_URI, rpm=200)

    def patched_fetch_fills(wallet):
        nonlocal delay
        fills, delay = fetch_fills_with_backoff(wallet, delay)
        return fills

    scanner._fetch_all_fills_from_api = patched_fetch_fills

    metrics = scanner.calculate_profitability(wallet_address)

    if not metrics:
        print("No metrics returned — wallet may be invalid or API failed.")
        return

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
    print(f"  Has activity:  {metrics.get('has_trading_activity')}")
    print(f"  Account value: ${metrics.get('account_value', 0):,.2f}")
    print(f"  Total PnL:     ${metrics.get('total_pnl_usdc', 0):,.2f}")
    print(f"  Win rate:      {metrics.get('win_rate_percentage', 0):.1f}%")
    print(f"  Trade count:   {metrics.get('trade_count', 0):,}")
    print(f"  Max drawdown:  {metrics.get('max_drawdown_percentage', 0):.1f}%")
    print(f"  Is bot:        {metrics.get('is_likely_bot')}")
    print(f"  Role:          {metrics.get('user_role')}")
    print(f"  Fee tier:      {metrics.get('fee_tier')}")
    print(f"  Open positions:{metrics.get('open_positions_count', 0)}")

    if metrics.get("open_positions"):
        print("\n  Open positions:")
        for pos in metrics["open_positions"]:
            print(
                f"    {pos['asset']} {pos['direction']} "
                f"size={pos['size']} "
                f"entry={pos['entry_price']} "
                f"uPnL=${pos['unrealized_pnl']}"
            )

    if not save_to_mongo:
        print("\nMongo save skipped (--dry-run mode)")
        return metrics

    client = MongoClient(MONGO_URI)
    db     = client[DB_NAME]
    coll   = db["profitability_metrics"]

    result = coll.update_one(
        {"wallet_address": wallet_address},
        {"$set": metrics},
        upsert=True
    )

    if result.upserted_id:
        print(f"\nInserted new document into profitability_metrics")
    else:
        print(f"\nUpdated existing document in profitability_metrics")

    client.close()
    print(f"Done at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return metrics


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scanSingleWallet.py <wallet_address> [--dry-run]")
        print("Example:")
        print("  python scanSingleWallet.py 0x6ba2ad09aa6629a423b59b71f3564d84ce66c001")
        print("  python scanSingleWallet.py 0x6ba2ad09aa6629a423b59b71f3564d84ce66c001 --dry-run")
        sys.exit(1)

    wallet  = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    scan_wallet(wallet, save_to_mongo=not dry_run)
