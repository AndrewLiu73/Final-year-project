import requests
import time
import math
from collections import defaultdict

# === CONFIG ===
symbols = {
    "BTCUSDT": {
        "category": "spot",
        "label": "Bybit Spot"
    },
    "BTCUSDT": {
        "category": "linear",  # perpetual
        "label": "Bybit Perpetual"
    }
}

min_btc = 10         # filter for orders ≥ 100 BTC
bucket_size = 100      # price bin size in USD
sleep_interval = 2     # loop delay (seconds)

ORDERBOOK_URL = "https://api.bybit.com/v5/market/orderbook"
TICKER_URL = "https://api.bybit.com/v5/market/tickers"

def get_live_price(category, symbol):
    """Get real-time BTC price"""
    response = requests.get(TICKER_URL, params={"category": category, "symbol": symbol})
    data = response.json()
    if data.get("retCode") == 0:
        return float(data["result"]["list"][0]["lastPrice"])
    else:
        print(f"[{symbol}] Error getting price:", data.get("retMsg"))
        return None

def get_orderbook(category, symbol):
    """Get order book data from Bybit"""
    response = requests.get(ORDERBOOK_URL, params={"category": category, "symbol": symbol})
    data = response.json()
    if data.get("retCode") == 0:
        return data["result"]
    else:
        print(f"[{symbol}] Error getting orderbook:", data.get("retMsg"))
        return None

def bucket_orders(order_list, btc_price):
    buckets = defaultdict(lambda: {"btc": 0, "usd": 0})
    for entry in order_list:
        price = float(entry[0])
        size = float(entry[1])
        usd_val = price * size

        bucket = math.floor(price / bucket_size) * bucket_size
        buckets[bucket]["btc"] += size
        buckets[bucket]["usd"] += usd_val

    filtered = {k: v for k, v in buckets.items() if v["usd"] >= (btc_price * min_btc)}
    return dict(sorted(filtered.items()))

def display_buckets(buckets, side, label):
    print(f"\n--- {label} {side.upper()} BUCKETS (≥ {min_btc} BTC worth) ---")
    if not buckets:
        print("No large clusters found.")
    for price_bin, data in buckets.items():
        print(f"${price_bin:<6}  Size: {data['btc']:.2f} BTC  Value: ${data['usd']:,.2f}")

def main_loop():
    while True:
        for symbol, info in symbols.items():
            category = info["category"]
            label = info["label"]

            btc_price = get_live_price(category, symbol)
            if btc_price is None:
                continue

            ob = get_orderbook(category, symbol)
            if ob is None:
                continue

            print(f"\n======= {label} ({symbol}) BTC: ${btc_price:,.2f} =======")

            bids = ob["b"]
            asks = ob["a"]

            bid_buckets = bucket_orders(bids, btc_price)
            ask_buckets = bucket_orders(asks, btc_price)

            display_buckets(bid_buckets, "bid", label)
            display_buckets(ask_buckets, "ask", label)

        print("\n" + "=" * 60 + "\n")
        time.sleep(sleep_interval)

if __name__ == "__main__":
    main_loop()
