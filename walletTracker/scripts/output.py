from pymongo import MongoClient
from typing import Optional
import os
from pathlib import Path
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent  # backend/.. = website/
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


def getFloatInput(prompt: str, allowNone: bool = False) -> Optional[float]:
    """Get float input from user with validation"""
    while True:
        value = input(prompt).strip()
        if allowNone and value == "":
            return None
        try:
            return float(value)
        except ValueError:
            print("Invalid input. Please enter a number.")


def getTopTraders():
    # MongoDB connection
    mongoUri = os.getenv("MONGO_URI")
    client = MongoClient(mongoUri)
    db = client.hyperliquid
    metricsCollection = db.profitability_metrics

    print("=" * 60)
    print("TOP 50 TRADERS FILTER")
    print("=" * 60)
    print("Leave blank to skip a filter\n")

    # User inputs
    print("--- Account Balance (USDC) ---")
    balanceMin = getFloatInput("Minimum balance: ", allowNone=True)
    balanceMax = getFloatInput("Maximum balance: ", allowNone=True)

    print("\n--- Win Rate (%) ---")
    winrateMin = getFloatInput("Minimum win rate %: ", allowNone=True)

    print("\n--- Profitability (PNL in USDC) ---")
    pnlMin = getFloatInput("Minimum PNL: ", allowNone=True)

    print("\n--- Max Drawdown (%) ---")
    drawdownMax = getFloatInput("Maximum drawdown %: ", allowNone=True)

    print("\n--- Profitability Status ---")
    filterProfitable = input("Show only profitable traders? (y/n, leave blank for all): ").strip().lower()

    # Build MongoDB query
    query = {"has_trading_activity": True}  # Only show traders with activity

    if balanceMin is not None or balanceMax is not None:
        query["account_value"] = {}
        if balanceMin is not None:
            query["account_value"]["$gte"] = balanceMin
        if balanceMax is not None:
            query["account_value"]["$lte"] = balanceMax

    if winrateMin is not None:
        query["win_rate_percentage"] = {"$gte": winrateMin}

    if pnlMin is not None:
        query["total_pnl_usdc"] = {"$gte": pnlMin}

    if drawdownMax is not None:
        query["max_drawdown_percentage"] = {"$lte": drawdownMax}

    if filterProfitable == 'y':
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
    traders = list(metricsCollection.find(query).sort("total_pnl_usdc", -1).limit(50))

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
    totalPnl = sum(t.get("total_pnl_usdc", 0) for t in traders)
    avgPnl = totalPnl / len(traders)
    avgBalance = sum(t.get("account_value", 0) for t in traders) / len(traders)
    avgWinrate = sum(t.get("win_rate_percentage", 0) for t in traders) / len(traders)
    avgDrawdown = sum(t.get("max_drawdown_percentage", 0) for t in traders) / len(traders)
    profitableCount = sum(1 for t in traders if t.get("total_pnl_usdc", 0) > 0)

    print(f"\nSummary Statistics:")
    print(f"  Total PNL: ${totalPnl:,.2f}")
    print(f"  Average PNL: ${avgPnl:,.2f}")
    print(f"  Average Balance: ${avgBalance:,.2f}")
    print(f"  Average Win Rate: {avgWinrate:.2f}%")
    print(f"  Average Drawdown: {avgDrawdown:.2f}%")
    print(f"  Top Trader PNL: ${traders[0].get('total_pnl_usdc', 0):,.2f}")
    print(f"  Profitable Traders: {profitableCount}/{len(traders)}")

    client.close()


if __name__ == "__main__":
    getTopTraders()
