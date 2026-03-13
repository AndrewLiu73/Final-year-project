from pymongo import MongoClient
import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


def plot_pnl_from_trades(wallet_address):
    """Plot PnL history directly from trade fills via API"""

    print(f"\nFetching trade history for {wallet_address}...")

    try:
        # Fetch fills from Hyperliquid API
        response = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "userFills", "user": wallet_address},
            timeout=15
        )

        if response.status_code != 200:
            print(f"API error: HTTP {response.status_code}")
            return

        fills = response.json()

        if not fills or len(fills) == 0:
            print("No trading history found for this wallet.")
            return

        print(f"Found {len(fills)} trades. Generating chart...\n")

    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    # Sort fills by timestamp
    sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))

    # Calculate cumulative PnL
    dates = []
    cumulative_pnl = []
    running_total = 0

    for fill in sorted_fills:
        timestamp = fill.get('time', 0)
        closed_pnl = float(fill.get('closedPnl', 0))

        # Convert timestamp (milliseconds) to datetime
        date = datetime.fromtimestamp(timestamp / 1000)
        running_total += closed_pnl

        dates.append(date)
        cumulative_pnl.append(running_total)

    # Calculate drawdown
    peak = cumulative_pnl[0]
    drawdown = []

    for pnl in cumulative_pnl:
        if pnl > peak:
            peak = pnl

        if peak > 0:
            dd = ((peak - pnl) / peak * 100)
        else:
            dd = 0
        drawdown.append(dd)

    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle(f'Trading Performance - {wallet_address[:10]}...{wallet_address[-8:]}',
                 fontsize=16, fontweight='bold')

    # Plot 1: Cumulative PnL
    ax1.plot(dates, cumulative_pnl, linewidth=2, color='#2E86AB')
    ax1.axhline(y=0, color='gray', linestyle='-', linewidth=0.5, alpha=0.5)
    ax1.fill_between(dates, cumulative_pnl, 0,
                     where=[p >= 0 for p in cumulative_pnl],
                     alpha=0.2, color='green', label='Profit')
    ax1.fill_between(dates, cumulative_pnl, 0,
                     where=[p < 0 for p in cumulative_pnl],
                     alpha=0.2, color='red', label='Loss')

    ax1.set_xlabel('Date', fontsize=12)
    ax1.set_ylabel('Cumulative PnL (USDC)', fontsize=12)
    ax1.set_title('Cumulative Profit & Loss', fontsize=14, fontweight='bold')
    ax1.legend(loc='best', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

    # Annotations
    if len(cumulative_pnl) > 0:
        ax1.annotate(f'Start: ${cumulative_pnl[0]:,.0f}',
                     xy=(dates[0], cumulative_pnl[0]),
                     xytext=(10, 10), textcoords='offset points',
                     fontsize=9, bbox=dict(boxstyle='round,pad=0.3',
                                           facecolor='yellow', alpha=0.5))
        ax1.annotate(f'Current: ${cumulative_pnl[-1]:,.0f}',
                     xy=(dates[-1], cumulative_pnl[-1]),
                     xytext=(-80, -20), textcoords='offset points',
                     fontsize=9, bbox=dict(boxstyle='round,pad=0.3',
                                           facecolor='yellow', alpha=0.5))

    # Plot 2: Drawdown
    ax2.fill_between(dates, drawdown, 0, alpha=0.3, color='red')
    ax2.plot(dates, drawdown, linewidth=2, color='#D62828')
    ax2.invert_yaxis()

    ax2.set_xlabel('Date', fontsize=12)
    ax2.set_ylabel('Drawdown (%)', fontsize=12)
    ax2.set_title('Drawdown from Peak', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')

    # Calculate statistics
    total_pnl = cumulative_pnl[-1] if cumulative_pnl else 0
    max_pnl = max(cumulative_pnl) if cumulative_pnl else 0
    min_pnl = min(cumulative_pnl) if cumulative_pnl else 0
    max_dd = max(drawdown) if drawdown else 0

    winning_trades = sum(1 for f in sorted_fills if float(f.get('closedPnl', 0)) > 0)
    losing_trades = sum(1 for f in sorted_fills if float(f.get('closedPnl', 0)) < 0)
    win_rate = (winning_trades / len(sorted_fills) * 100) if len(sorted_fills) > 0 else 0

    period_days = (dates[-1] - dates[0]).days if len(dates) > 1 else 0

    # Statistics box
    stats_text = f'Total Trades: {len(sorted_fills):,}\n'
    stats_text += f'Win Rate: {win_rate:.1f}%\n'
    stats_text += f'Total PnL: ${total_pnl:,.2f}\n'
    stats_text += f'Max PnL: ${max_pnl:,.2f}\n'
    stats_text += f'Min PnL: ${min_pnl:,.2f}\n'
    stats_text += f'Max Drawdown: {max_dd:.2f}%\n'
    stats_text += f'Period: {period_days} days'

    ax2.text(0.02, 0.02, stats_text, transform=ax2.transAxes,
             fontsize=10, verticalalignment='bottom',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    plt.tight_layout()

    # Save chart
    filename = f"pnl_chart_{wallet_address[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"Chart saved as: {filename}")

    plt.show()


def main():
    """Main function to run PnL chart viewer"""
    print("\n" + "=" * 80)
    print("WALLET PNL CHART VIEWER (Live from API)")
    print("=" * 80)

    wallet = input("\nEnter wallet address: ").strip()

    if not wallet:
        print("Invalid wallet address.")
        return

    plot_pnl_from_trades(wallet)


if __name__ == "__main__":
    main()
