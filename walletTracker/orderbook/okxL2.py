import requests
import time
from collections import defaultdict
import math

# === API Endpoints ===
ORDERBOOK_URL = "https://www.okx.com/api/v5/market/books-full"
TICKER_URL = "https://www.okx.com/api/v5/market/ticker"

# === Instruments to Track ===
instruments = {
    "BTC-USDT": "Spot",
    "BTC-USDT-SWAP": "Perpetual"
}

# === Thresholds ===
min_btc = 100  # Minimum BTC worth
depth_size = 5000
bucket_size = 100  # USD bin size (e.g., 86000–86099 → 86000)

def get_current_btc_price(instId):
    response = requests.get(TICKER_URL, params={"instId": instId})
    data = response.json()
    if data.get("code") == "0":
        return float(data["data"][0]["last"])
    else:
        print(f"[{instId}] Error fetching BTC price:", data.get("msg"))
        return None

def get_orderbook(instId):
    response = requests.get(ORDERBOOK_URL, params={"instId": instId, "sz": depth_size})
    data = response.json()
    if data.get("code") == "0":
        return data["data"][0]
    else:
        print(f"[{instId}] Error fetching orderbook:", data.get("msg"))
        return None

def bucket_orders(orders, side, btc_price):
    buckets = defaultdict(lambda: {"btc": 0, "usd": 0})
    for entry in orders:
        price = float(entry[0])
        size = float(entry[1])
        usd_val = price * size

        bucket = math.floor(price / bucket_size) * bucket_size
        buckets[bucket]["btc"] += size
        buckets[bucket]["usd"] += usd_val

    # Filter out buckets below threshold
    filtered = {k: v for k, v in buckets.items() if v["usd"] >= (btc_price * min_btc)}

    return dict(sorted(filtered.items()))  # sort by price ascending

def display_buckets(buckets, side, label):
    print(f"\n--- {label} {side.upper()} BUCKETS (≥ {min_btc} BTC worth per bin) ---")
    if not buckets:
        print("No large clusters found.")
    for price_bin, data in buckets.items():
        print(f"${price_bin:<6}  Size: {data['btc']:.2f} BTC  Value: ${data['usd']:,.2f}")

def main_loop():
    while True:
        for instId, label in instruments.items():
            btc_price = get_current_btc_price(instId)
            if btc_price is None:
                continue

            orderbook = get_orderbook(instId)
            if orderbook is None:
                continue

            print(f"\n======= {label} ({instId}) BTC: ${btc_price:,.2f} =======")

            bids = orderbook["bids"]
            asks = orderbook["asks"]

            bid_buckets = bucket_orders(bids, "bid", btc_price)
            ask_buckets = bucket_orders(asks, "ask", btc_price)

            display_buckets(bid_buckets, "bid", label)
            display_buckets(ask_buckets, "ask", label)

        print("\n" + "=" * 60 + "\n")
        time.sleep(2)

if __name__ == "__main__":
    main_loop()
