import aiohttp
import asyncio
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone

from hyperliquid.info import Info
from hyperliquid.utils import constants

# --- Configuration
HYPERLIQUID_API = constants.MAINNET_API_URL
GOOD_TRADERS_FILE = "data/goodTraders.txt"
RATE_LIMIT_DELAY = 1.5   # seconds between requests
LOOP_DELAY = 60          # seconds between analysis rounds
TARGET_COINS = ["BTC", "HYPE"]
MAX_RETRIES = 3

# Initialize Hyperliquid SDK client
info = Info(HYPERLIQUID_API, skip_ws=True)

# Data models
@dataclass
class Position:
    coin: str
    size: float            # positive for long, negative for short
    entry_price: float
    current_value: float
    unrealized_pnl: float

@dataclass
class Order:
    coin: str
    side: str              # 'B' = buy, 'A' = sell
    size: float
    price: float
    order_type: str
    reduce_only: bool
    oid: str

@dataclass
class Fill:
    coin: str
    side: str
    size: float
    price: float
    reduce_only: bool
    order_type: str
    timestamp: int

@dataclass
class OrderAnalysis:
    coin: str
    analysis_type: str     # 'TP','SL','ENTRY','DCA','MKTCLOSE'
    confidence: str        # 'HIGH','MEDIUM','LOW'
    detail: str

# Utilities

def load_wallets() -> List[str]:
    path = Path(GOOD_TRADERS_FILE)
    if not path.exists():
        raise FileNotFoundError(f"{GOOD_TRADERS_FILE} not found")
    return [line.strip() for line in path.read_text().splitlines() if line.strip().startswith("0x")]

async def fetch_positions(session, wallet: str) -> List[dict]:
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(HYPERLIQUID_API, json={"type": "clearinghouseState", "user": wallet}) as resp:
                if resp.status == 200:
                    return (await resp.json()).get("assetPositions", [])
        except Exception:
            await asyncio.sleep(2 ** attempt)
    return []

async def fetch_orders(session, wallet: str) -> List[dict]:
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(HYPERLIQUID_API, json={"type": "openOrders", "user": wallet}) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            await asyncio.sleep(2 ** attempt)
    return []

async def fetch_fills(wallet: str, since_ms: int) -> (List[Fill], int):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # user_fills_by_time returns a list of fill dicts
    raw_fills = info.user_fills_by_time(wallet, start_time=since_ms, end_time=now_ms)
    fills = []
    for f in raw_fills:
        fills.append(Fill(
            coin=f.get("coin"), side=f.get("side"), size=float(f.get("sz", 0)),
            price=float(f.get("px", 0)), reduce_only=bool(f.get("reduceOnly", False)),
            order_type=f.get("orderType", ""), timestamp=f.get("time", 0)
        ))
    return fills, now_ms

# Parsing

def parse_positions(data: List[dict]) -> Dict[str, Position]:
    out = {}
    for item in data:
        p = item.get("position", {})
        coin = p.get("coin")
        size = float(p.get("szi", 0))
        if size == 0:
            continue
        entry = float(p.get("entryPx", 0))
        val = float(p.get("positionValue", 0))
        pnl = float(p.get("unrealizedPnl", 0))
        out[coin] = Position(coin, size, entry, val, pnl)
    return out


def parse_orders(data: List[dict]) -> List[Order]:
    out = []
    for o in data:
        px_raw = o.get("px") or o.get("limitPx") or 0
        out.append(Order(
            coin=o.get("coin"), side=o.get("side"), size=float(o.get("sz", 0)),
            price=float(px_raw), order_type=o.get("orderType", ""),
            reduce_only=bool(o.get("reduceOnly", False)), oid=str(o.get("oid"))
        ))
    return out

# Analysis

def analyze_orders_and_fills(positions: Dict[str, Position], orders: List[Order], fills: List[Fill]) -> List[OrderAnalysis]:
    results: List[OrderAnalysis] = []
    # Limit-order TP/SL
    for o in orders:
        pos = positions.get(o.coin)
        if pos and o.reduce_only:
            is_long = pos.size > 0
            est_price = abs(pos.current_value / pos.size) if pos.current_value and pos.size else pos.entry_price
            cond = (is_long and o.side == 'A') or (not is_long and o.side == 'B')
            if cond:
                tp = (is_long and o.price > est_price) or (not is_long and o.price < est_price)
                ttype = "TP" if tp else "SL"
                results.append(OrderAnalysis(o.coin, ttype, "HIGH", f"Limit {'sell' if o.side=='A' else 'buy'} at {o.price:.2f}"))
    # Market closes via fills
    for f in fills:
        if f.reduce_only and f.order_type.lower() == "market":
            side = "sell" if f.side == 'A' else "buy"
            results.append(OrderAnalysis(f.coin, "MKTCLOSE", "HIGH", f"Market close {side} {f.size:.4f}@{f.price:.2f}"))
    return results

async def analyze_wallet(session, wallet: str, last_fill_ms: int) -> (List[OrderAnalysis], int):
    pos_data = await fetch_positions(session, wallet)
    ord_data = await fetch_orders(session, wallet)
    positions = parse_positions(pos_data)
    orders = parse_orders(ord_data)
    fills, new_ms = await fetch_fills(wallet, last_fill_ms)
    analyses = analyze_orders_and_fills(positions, orders, fills)
    return analyses, new_ms

# Main loop
async def main():
    wallets = load_wallets()
    print(f"Starting analysis on {len(wallets)} wallets...")
    # init fill cursors 5m ago
    now = datetime.now(timezone.utc)
    last_ms = {w: int((now - timedelta(minutes=5)).timestamp() * 1000) for w in wallets}

    async with aiohttp.ClientSession() as session:
        while True:
            for w in wallets:
                analyses, last_ms[w] = await analyze_wallet(session, w, last_ms[w])
                if analyses:
                    print(f"Wallet {w} analysis:")
                    for a in analyses:
                        print(f"  {a.analysis_type} [{a.confidence}] {a.coin} → {a.detail}")
                else:
                    print(f"Wallet {w}: no TP/SL/market-close events.")
                await asyncio.sleep(RATE_LIMIT_DELAY)
            print("--- Waiting for next round ---\n")
            await asyncio.sleep(LOOP_DELAY)

if __name__ == "__main__":
    asyncio.run(main())
