import requests
import time
import math
from collections import defaultdict

# === Config ===
symbol = "BTCUSDT"
bucket_size = 100
min_btc = 100
sleep_interval = 2

ORDERBOOK_URL = "https://api.binance.com/api/v3/depth"
TICKER_URL = "https://api.binance.com/api/v3/ticker/price"

def get_live_price(symbol):
    response = requests.get(TICKER_URL, params={"symbol": symbol})
    data = response.json()
    return float(data["price"])

def get_orderbook(symbol):
    response = requests.get(ORDERBOOK_URL, params={"symbol": symbol, "limit": 5000})
    return response.json()

def bucket_orders(orders, btc_price):
    buckets = defaultdict(lambda: {"btc": 0, "usd": 0})
    for entry in orders:
        price = float(entry[0])
        qty = float(entry[1])
        usd_val = price * qty

        bucket = math.floor(price / bucket_size) * bucket_size
        buckets[bucket]["btc"] += qty
        buckets[bucket]["usd"] += usd_val

    filtered = {k: v for k, v in buckets.items() if v["usd"] >= (btc_price * min_btc)}
    return dict(sorted(filtered.items()))

def display_buckets(buckets, side):
    print(f"\n--- BINANCE {side.upper()} BUCKETS (≥ {min_btc} BTC worth) ---")
    if not buckets:
        print("No large clusters found.")
    for price_bin, data in buckets.items():
        print(f"${price_bin:<6}  Size: {data['btc']:.2f} BTC  Value: ${data['usd']:,.2f}")

def main_loop():
    while True:
        try:
            btc_price = get_live_price(symbol)
            orderbook = get_orderbook(symbol)

            print(f"\n======= BINANCE BTCUSDT — BTC Price: ${btc_price:,.2f} =======")

            bids = orderbook["bids"]
            asks = orderbook["asks"]

            bid_buckets = bucket_orders(bids, btc_price)
            ask_buckets = bucket_orders(asks, btc_price)

            display_buckets(bid_buckets, "bid")
            display_buckets(ask_buckets, "ask")

            print("\n" + "=" * 60 + "\n")
            time.sleep(sleep_interval)
        except Exception as e:
            print("Error:", e)
            time.sleep(sleep_interval)

if __name__ == "__main__":
    main_loop()
