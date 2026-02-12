from pymongo import MongoClient
from typing import Optional
import os
from pathlib import Path
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent  # backend/.. = website/
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


def get_float_input(prompt: str, allow_none: bool = False) -> Optional[float]:
    """Get float input from user with validation"""
    while True:
        value = input(prompt).strip()
        if allow_none and value == "":
            return None
        try:
            return float(value)
        except ValueError:
            print("Invalid input. Please enter a number.")


def get_top_traders():
    # MongoDB connection
    mongo_uri = os.getenv("MONGO_URI")
    client = MongoClient(mongo_uri)
    db = client.hyperliquid
    metrics_collection = db.profitability_metrics

    print("=" * 60)
    print("TOP 50 TRADERS FILTER")
    print("=" * 60)
    print("Leave blank to skip a filter\n")

    # User inputs
    print("--- Account Balance (USDC) ---")
    balance_min = get_float_input("Minimum balance: ", allow_none=True)
    balance_max = get_float_input("Maximum balance: ", allow_none=True)

    print("\n--- Win Rate (%) ---")
    winrate_min = get_float_input("Minimum win rate %: ", allow_none=True)

    print("\n--- Profitability (PNL in USDC) ---")
    pnl_min = get_float_input("Minimum PNL: ", allow_none=True)

    print("\n--- Max Drawdown (%) ---")
    drawdown_max = get_float_input("Maximum drawdown %: ", allow_none=True)

    print("\n--- Profitability Status ---")
    filter_profitable = input("Show only profitable traders? (y/n, leave blank for all): ").strip().lower()

    # Build MongoDB query
    query = {"has_trading_activity": True}  # Only show traders with activity

    if balance_min is not None or balance_max is not None:
        query["account_value"] = {}
        if balance_min is not None:
            query["account_value"]["$gte"] = balance_min
        if balance_max is not None:
            query["account_value"]["$lte"] = balance_max

    if winrate_min is not None:
        query["win_rate_percentage"] = {"$gte": winrate_min}

    if pnl_min is not None:
        query["total_pnl_usdc"] = {"$gte": pnl_min}

    if drawdown_max is not None:
        query["max_drawdown_percentage"] = {"$lte": drawdown_max}

    if filter_profitable == 'y':
        query["total_pnl_usdc"] = query.get("total_pnl_usdc", {})
        if isinstance(query["total_pnl_usdc"], dict):
            query["total_pnl_usdc"]["$gt"] = max(query["total_pnl_usdc"].get("$gte", 0), 0)
        else:
            query["total_pnl_usdc"] = {"$gt": 0}

    # Query database and sort by PNL descending
    print("\n" + "=" * 60)
    print("FETCHING RESULTS...")
    print("=" * 60 + "\n")

    # Query MongoDB
    traders = list(metrics_collection.find(query).sort("total_pnl_usdc", -1).limit(50))

    # Display results
    if not traders:
        print("No traders found matching your criteria.")
        client.close()
        return

    print(f"Found {len(traders)} traders matching criteria\n")
    print("=" * 125)
    print(f"{'Rank':<6}{'Address':<45}{'PNL (USDC)':<15}{'Balance':<15}{'Win Rate':<12}{'Drawdown':<12}")
    print("=" * 125)

    for rank, trader in enumerate(traders, 1):
        address = trader.get("wallet_address", "N/A")
        pnl = trader.get("total_pnl_usdc", 0)
        balance = trader.get("account_value", 0)
        winrate = trader.get("win_rate_percentage", 0)
        drawdown = trader.get("max_drawdown_percentage", 0)

        print(f"{rank:<6}{address:<45}{pnl:>12,.2f}   {balance:>12,.2f}   {winrate:>8.2f}%   {drawdown:>8.2f}%")

    print("=" * 125)

    # Summary stats
    total_pnl = sum(t.get("total_pnl_usdc", 0) for t in traders)
    avg_pnl = total_pnl / len(traders)
    avg_balance = sum(t.get("account_value", 0) for t in traders) / len(traders)
    avg_winrate = sum(t.get("win_rate_percentage", 0) for t in traders) / len(traders)
    avg_drawdown = sum(t.get("max_drawdown_percentage", 0) for t in traders) / len(traders)
    profitable_count = sum(1 for t in traders if t.get("total_pnl_usdc", 0) > 0)

    print(f"\nSummary Statistics:")
    print(f"  Total PNL: ${total_pnl:,.2f}")
    print(f"  Average PNL: ${avg_pnl:,.2f}")
    print(f"  Average Balance: ${avg_balance:,.2f}")
    print(f"  Average Win Rate: {avg_winrate:.2f}%")
    print(f"  Average Drawdown: {avg_drawdown:.2f}%")
    print(f"  Top Trader PNL: ${traders[0].get('total_pnl_usdc', 0):,.2f}")
    print(f"  Profitable Traders: {profitable_count}/{len(traders)}")

    client.close()


if __name__ == "__main__":
    get_top_traders()
