from hyperliquid.info import Info
from hyperliquid.utils import constants
from datetime import datetime

# --- Setup
info = Info(constants.MAINNET_API_URL, skip_ws=True)
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime.now()

# --- Load trader addresses
with open("goodTraders.txt") as f:
    traders = [line.strip() for line in f if line.strip()]

# --- Fetch fills
def fetch_fills(trader):
    start_ms = int(START_DATE.timestamp() * 1000)
    end_ms = int(END_DATE.timestamp() * 1000)
    return info.user_fills_by_time(trader, start_time=start_ms, end_time=end_ms)

# --- Count flips per coin
def analyze_coin(fills, coin):
    coin_fills = [f for f in fills if f["coin"] == coin]
    if not coin_fills:
        return 0, None, None

    sorted_fills = sorted(coin_fills, key=lambda f: f["time"])
    flips = 0
    last_side = sorted_fills[0]["side"]
    for fill in sorted_fills[1:]:
        if fill["side"] != last_side:
            flips += 1
            last_side = fill["side"]

    first_time = datetime.fromtimestamp(sorted_fills[0]["time"] / 1000)
    last_time = datetime.fromtimestamp(sorted_fills[-1]["time"] / 1000)
    return flips, first_time, last_time

# --- Main loop
for trader in traders:
    try:
        fills = fetch_fills(trader)

        btc_flips, btc_start, btc_end = analyze_coin(fills, "BTC")
        hype_flips, hype_start, hype_end = analyze_coin(fills, "HYPE")

        print(f"\nTrader: {trader}")
        if btc_flips > 0:
            print(f"  BTC  → {btc_flips} flips | {btc_start:%Y-%m-%d} → {btc_end:%Y-%m-%d}")
        else:
            print("  BTC  → No trades")

        if hype_flips > 0:
            print(f"  HYPE → {hype_flips} flips | {hype_start:%Y-%m-%d} → {hype_end:%Y-%m-%d}")
        else:
            print("  HYPE → No trades")

    except Exception as e:
        print(f"{trader}: Error fetching data ({str(e)})")
