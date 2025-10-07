import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from hyperliquid.info import Info
from hyperliquid.utils import constants

# --- Setup
info = Info(constants.MAINNET_API_URL, skip_ws=True)
trader_address = "0x1e771e1b95c86491299d6e2a5c3b3842d03b552e"

# --- Fetch user state
print("Fetching user state...\n")
user_state = info.user_state(trader_address)

account_value = float(user_state["marginSummary"]["accountValue"])
print(f"Account Value: ${account_value:,.2f}\n")

# --- Display open positions
positions = user_state.get("assetPositions", [])
if not positions:
    print("No open positions found.")
else:
    print("Open Positions:")
    for pos in positions:
        if pos["type"] != "oneWay":
            continue

        position_data = pos["position"]
        coin = position_data["coin"]
        size = position_data["szi"]
        entry_price = position_data["entryPx"]
        liq_px = position_data["liquidationPx"]
        unrealized_pnl = position_data["unrealizedPnl"]
        roe = float(position_data["returnOnEquity"]) * 100
        margin_used = position_data["marginUsed"]

        print(f"Coin: {coin}")
        print(f"  Size: {size}")
        print(f"  Entry Price: ${entry_price}")
        print(f"  Liquidation Price: ${liq_px}")
        print(f"  Unrealized PnL: ${unrealized_pnl}")
        print(f"  ROE: {roe:.2f}%")
        print(f"  Margin Used: ${margin_used}")
        print("-" * 40)

# --- Fetch fills with batched API calls
print("Fetching trade history in batches...")
all_fills = []
max_calls = 5
trades_per_call = 2000
total_target = 10000

for call_num in range(1, max_calls + 1):
    print(f"API Call {call_num}/{max_calls}: Fetching up to {trades_per_call} trades...")

    try:
        # Get fills with limit parameter if API supports it
        # Note: Check your Hyperliquid API documentation for exact parameter name
        # This might need to be adjusted based on the actual API specification
        fills_batch = info.user_fills(trader_address)

        if not fills_batch:
            print(f"  No trades returned in batch {call_num}")
            break

        # If this is not the first call, we need to get trades after the last timestamp
        if call_num > 1 and all_fills:
            # Filter out trades we already have (assuming API returns newest first)
            last_timestamp = min(trade["time"] for trade in all_fills)
            fills_batch = [trade for trade in fills_batch if trade["time"] < last_timestamp]

        if not fills_batch:
            print(f"  No new trades found in batch {call_num}")
            break

        all_fills.extend(fills_batch)
        print(f"  Retrieved {len(fills_batch)} trades (Total: {len(all_fills)})")

        # Stop if we've reached our target or got less than expected (end of data)
        if len(all_fills) >= total_target or len(fills_batch) < trades_per_call:
            break

    except Exception as e:
        print(f"  Error in API call {call_num}: {e}")
        break

# Remove duplicates based on trade time and other identifying info
seen_trades = set()
unique_fills = []
for trade in all_fills:
    trade_id = (trade["time"], trade["coin"], trade["side"], trade["sz"], trade["px"])
    if trade_id not in seen_trades:
        seen_trades.add(trade_id)
        unique_fills.append(trade)

fills = unique_fills
print(f"\nTotal unique trades retrieved: {len(fills)}")

if not fills:
    print("No trades found.")
    fills = []
else:
    fills.sort(key=lambda x: x["time"])  # Sort from oldest to newest

    # Analysis of data completeness
    if len(fills) >= total_target:
        print(f"✅ Retrieved {len(fills)} trades (reached target of {total_target})")
        print("   This represents the maximum data collected via batched API calls.")
    elif len(fills) >= 8000:  # Close to target
        print(f"✅ Retrieved {len(fills)} trades (near maximum via API)")
        print("   This likely represents most or all of your trading history.")
    else:
        print(f"✅ Retrieved {len(fills)} trades (complete history)")
        print("   All available trades have been collected.")

# --- Build trade list with PnL and cumulative timeline
trades_data = []
timestamps = []
cumulative_pnl = 0.0
pnl_timeline = []

# Trading direction analysis
buy_count = 0
sell_count = 0
buy_volume = 0.0
sell_volume = 0.0

for trade in fills:
    closed_pnl = float(trade.get("closedPnl", 0))
    cumulative_pnl += closed_pnl
    trade_time = datetime.fromtimestamp(trade["time"] / 1000)

    # Analyze trading direction
    side = trade["side"].lower()
    size = float(trade["sz"])

    if side == "b":  # Buy
        buy_count += 1
        buy_volume += size
    elif side == "a":  # Sell/Short
        sell_count += 1
        sell_volume += size

    trades_data.append({
        "time": trade["time"],
        "coin": trade["coin"],
        "side": trade["side"],
        "size": trade["sz"],
        "price": trade["px"],
        "closedPnl": closed_pnl
    })

    pnl_timeline.append(cumulative_pnl)
    timestamps.append(trade_time)

# --- Calculate trading bias
total_trades = buy_count + sell_count
if total_trades > 0:
    buy_percentage = (buy_count / total_trades) * 100
    sell_percentage = (sell_count / total_trades) * 100

    # Volume-based bias
    total_volume = buy_volume + sell_volume
    if total_volume > 0:
        buy_volume_percentage = (buy_volume / total_volume) * 100
        sell_volume_percentage = (sell_volume / total_volume) * 100
    else:
        buy_volume_percentage = sell_volume_percentage = 0

    # Buy/Short ratio
    if sell_count > 0:
        buy_to_sell_ratio = buy_count / sell_count
    else:
        buy_to_sell_ratio = float('inf') if buy_count > 0 else 0
else:
    buy_percentage = sell_percentage = 0
    buy_volume_percentage = sell_volume_percentage = 0
    buy_to_sell_ratio = 0

# --- Save to trades_with_pnl.json
file_path = "data/trades_with_pnl.json"
try:
    with open(file_path, "r") as f:
        all_trades = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    all_trades = {}

all_trades[trader_address.lower()] = trades_data

with open(file_path, "w") as f:
    json.dump(all_trades, f, indent=2)

print(f"\nSaved {len(trades_data)} trades with PnL to trades_with_pnl.json.")

# --- Show total PnL and trading statistics
print(f"\nTotal Realized (Closed) PnL: ${cumulative_pnl:.2f}")
print(f"Total fills processed: {len(fills)}")

if fills:  # Only print times if there are fills
    print("First trade time:", datetime.fromtimestamp(fills[0]['time'] / 1000))
    print("Last trade time: ", datetime.fromtimestamp(fills[-1]['time'] / 1000))

    # --- Trading Direction Analysis
    print("\n" + "=" * 50)
    print("TRADING DIRECTION ANALYSIS")
    print("=" * 50)

    print(f"\nTrade Count Analysis:")
    print(f"  Buy trades: {buy_count} ({buy_percentage:.1f}%)")
    print(f"  Sell/Short trades: {sell_count} ({sell_percentage:.1f}%)")
    print(f"  Total trades: {total_trades}")

    print(f"\nVolume Analysis:")
    print(f"  Buy volume: {buy_volume:.4f} ({buy_volume_percentage:.1f}%)")
    print(f"  Sell/Short volume: {sell_volume:.4f} ({sell_volume_percentage:.1f}%)")
    print(f"  Total volume: {total_volume:.4f}")

    print(f"\nDirection Bias:")
    if buy_to_sell_ratio == float('inf'):
        print(f"  Buy/Sell Ratio: ∞ (Only buy trades)")
        print(f"  Direction Bias: 100% BULLISH")
    elif buy_to_sell_ratio == 0:
        print(f"  Buy/Sell Ratio: 0 (Only sell trades)")
        print(f"  Direction Bias: 100% BEARISH")
    else:
        print(f"  Buy/Sell Ratio: {buy_to_sell_ratio:.2f}")
        if buy_percentage > 60:
            bias = "BULLISH"
        elif sell_percentage > 60:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
        print(f"  Direction Bias: {bias} ({buy_percentage:.1f}% buys vs {sell_percentage:.1f}% sells)")

else:
    print("No trade history available.")

# --- Plot cumulative PnL over time
if pnl_timeline:
    plt.figure(figsize=(12, 6))
    plt.plot(timestamps, pnl_timeline, marker='o', markersize=2, linewidth=1)

    plt.title(f"Cumulative Realized PnL Over Time ({len(fills)} trades)")
    plt.xlabel("Time")
    plt.ylabel("Cumulative Closed PnL (USD)")

    plt.grid(True, alpha=0.3)

    # Format x-axis with readable date/time
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gcf().autofmt_xdate()  # Auto rotate & align dates

    # Add final PnL value as text on plot
    plt.text(0.02, 0.98, f'Final PnL: ${cumulative_pnl:.2f}',
             transform=plt.gca().transAxes, fontsize=12,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    plt.tight_layout()
    plt.show()
else:
    print("No PnL data available to plot.")