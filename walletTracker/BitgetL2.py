import requests
import time
import math
from collections import defaultdict

# === Config ===
symbol = "BTCUSDT"
bucket_size = 100
min_btc = 10
sleep_interval = 2

# === Correct Bitget Endpoints (for Spot Market) ===
ORDERBOOK_URL =  "https://api.bitget.com/api/v2/spot/market/orderbook?symbol=BTCUSDT&type=step0&limit=150"
TICKER_URL = "https://api.bitget.com/api/v2/spot/market/tickers"

def get_live_price(symbol):
    try:
        response = requests.get(TICKER_URL, params={"symbol": symbol})
        if response.status_code != 200:
            print(f"Error fetching BTC price: HTTP {response.status_code}")
            return None
        data = response.json()
        if data.get("code") == "00000":
            return float(data["data"][0]["lastPr"])
        else:
            print("Error getting BTC price:", data.get("msg"))
            return None
    except Exception as e:
        print("Exception in get_live_price():", e)
        return None

def get_orderbook(symbol):
    try:
        response = requests.get(ORDERBOOK_URL, params={"symbol": symbol, "type": "step0", "limit": 1000})
        if response.status_code != 200:
            print(f"Error fetching orderbook: HTTP {response.status_code}")
            return None
        data = response.json()
        if data.get("code") == "00000":
            return data["data"]
        else:
            print("Error fetching orderbook:", data.get("msg"))
            return None
    except Exception as e:
        print("Exception in get_orderbook():", e)
        return None

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
    print(f"\n--- BITGET {side.upper()} BUCKETS (≥ {min_btc} BTC worth) ---")
    if not buckets:
        print("No large clusters found.")
    for price_bin, data in buckets.items():
        print(f"${price_bin:<6}  Size: {data['btc']:.2f} BTC  Value: ${data['usd']:,.2f}")

def main_loop():
    while True:
        try:
            btc_price = get_live_price(symbol)
            orderbook = get_orderbook(symbol)

            if btc_price is None or orderbook is None:
                time.sleep(sleep_interval)
                continue

            print(f"\n======= BITGET BTCUSDT — BTC Price: ${btc_price:,.2f} =======")

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
