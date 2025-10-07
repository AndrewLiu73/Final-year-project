import aiohttp
import asyncio
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import List, Dict, Optional

HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"
GOOD_TRADERS_FILE = "goodTraders.txt"
RATE_LIMIT_DELAY = 1.5  # seconds between wallet requests
LOOP_DELAY = 60  # delay between summary refreshes
TARGET_COINS = ["BTC", "HYPE"]
MAX_RETRIES = 3


@dataclass
class Position:
    coin: str
    size: float  # positive for long, negative for short
    entry_price: float
    current_value: float
    unrealized_pnl: float


@dataclass
class Order:
    coin: str
    side: str  # 'B' for buy, 'A' for sell
    size: float
    price: float
    order_type: str
    order_id: str


@dataclass
class OrderAnalysis:
    coin: str
    order: Order
    position: Optional[Position]
    analysis_type: str  # 'TP', 'SL', 'ENTRY', 'DCA', 'UNKNOWN'
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'
    reason: str


def load_wallets():
    path = Path(GOOD_TRADERS_FILE)
    if not path.exists():
        raise FileNotFoundError(f"{GOOD_TRADERS_FILE} not found")
    with path.open() as f:
        return [line.strip() for line in f if line.strip().startswith("0x") and len(line.strip()) == 42]


async def fetch_positions(session, wallet):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                    HYPERLIQUID_API,
                    json={"type": "clearinghouseState", "user": wallet}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("assetPositions", [])
                elif resp.status == 422:
                    return []
                else:
                    print(f"[{wallet}] Error fetching positions: {resp.status}")
        except Exception as e:
            print(f"[{wallet}] Exception fetching positions: {e}")

        await asyncio.sleep(2 ** attempt)
    return []


async def fetch_open_orders(session, wallet):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                    HYPERLIQUID_API,
                    json={"type": "openOrders", "user": wallet}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 429:
                    print(f"[{wallet}] Rate limited, retrying...")
                    await asyncio.sleep(2 ** attempt)
                else:
                    print(f"[{wallet}] Error fetching orders: {resp.status}")
        except Exception as e:
            print(f"[{wallet}] Exception fetching orders: {e}")

        await asyncio.sleep(2 ** attempt)
    return []


def parse_positions(positions_data) -> Dict[str, Position]:
    positions = {}
    for pos_data in positions_data:
        pos = pos_data.get("position", {})
        coin = pos.get("coin")
        szi = float(pos.get("szi", 0))

        if szi == 0:
            continue

        entry_price = float(pos.get("entryPx", 0))
        position_value = float(pos.get("positionValue", 0))
        unrealized_pnl = float(pos.get("unrealizedPnl", 0))

        positions[coin] = Position(
            coin=coin,
            size=szi,
            entry_price=entry_price,
            current_value=position_value,
            unrealized_pnl=unrealized_pnl
        )

    return positions


def parse_orders(orders_data) -> List[Order]:
    orders = []
    for order_data in orders_data:
        orders.append(Order(
            coin=order_data.get("coin"),
            side=order_data.get("side"),
            size=float(order_data.get("sz", 0)),
            price=float(order_data.get("limitPx", 0)),
            order_type=order_data.get("orderType", ""),
            order_id=order_data.get("oid", "")
        ))
    return orders


def analyze_order(order: Order, position: Optional[Position]) -> OrderAnalysis:
    if not position:
        return OrderAnalysis(
            coin=order.coin,
            order=order,
            position=None,
            analysis_type="ENTRY",
            confidence="HIGH",
            reason="No existing position - likely entry order"
        )

    position_is_long = position.size > 0
    order_is_buy = order.side == 'B'

    # Estimate current price from position data
    if position.current_value != 0 and position.size != 0:
        estimated_current_price = abs(position.current_value / position.size)
    else:
        estimated_current_price = position.entry_price

    # If position is long and order is sell (or position is short and order is buy)
    # this could be a closing order (TP/SL)
    if (position_is_long and not order_is_buy) or (not position_is_long and order_is_buy):
        # For long positions: TP is above current price, SL is below
        # For short positions: TP is below current price, SL is above
        if position_is_long:
            if order.price > estimated_current_price:
                return OrderAnalysis(
                    coin=order.coin,
                    order=order,
                    position=position,
                    analysis_type="TP",
                    confidence="HIGH",
                    reason=f"Long position, sell order above current price (~${estimated_current_price:.2f})"
                )
            else:
                return OrderAnalysis(
                    coin=order.coin,
                    order=order,
                    position=position,
                    analysis_type="SL",
                    confidence="HIGH",
                    reason=f"Long position, sell order below current price (~${estimated_current_price:.2f})"
                )
        else:  # Short position
            if order.price < estimated_current_price:
                return OrderAnalysis(
                    coin=order.coin,
                    order=order,
                    position=position,
                    analysis_type="TP",
                    confidence="HIGH",
                    reason=f"Short position, buy order below current price (~${estimated_current_price:.2f})"
                )
            else:
                return OrderAnalysis(
                    coin=order.coin,
                    order=order,
                    position=position,
                    analysis_type="SL",
                    confidence="HIGH",
                    reason=f"Short position, buy order above current price (~${estimated_current_price:.2f})"
                )

    # Same direction as position - need to determine if it's DCA or regular entry
    else:
        price_diff_pct = abs(order.price - estimated_current_price) / estimated_current_price * 100

        # If order price is significantly below current price (for longs) or above (for shorts)
        # it's likely a DCA/scale-in order
        if position_is_long and order.price < estimated_current_price:
            if price_diff_pct > 5:  # More than 5% below current price
                return OrderAnalysis(
                    coin=order.coin,
                    order=order,
                    position=position,
                    analysis_type="DCA",
                    confidence="HIGH",
                    reason=f"Long position, buy order {price_diff_pct:.1f}% below current price - likely DCA/scale-in"
                )
            else:
                return OrderAnalysis(
                    coin=order.coin,
                    order=order,
                    position=position,
                    analysis_type="ENTRY",
                    confidence="MEDIUM",
                    reason=f"Long position, buy order close to current price - likely adding to position"
                )
        elif not position_is_long and order.price > estimated_current_price:
            if price_diff_pct > 5:  # More than 5% above current price
                return OrderAnalysis(
                    coin=order.coin,
                    order=order,
                    position=position,
                    analysis_type="DCA",
                    confidence="HIGH",
                    reason=f"Short position, sell order {price_diff_pct:.1f}% above current price - likely DCA/scale-in"
                )
            else:
                return OrderAnalysis(
                    coin=order.coin,
                    order=order,
                    position=position,
                    analysis_type="ENTRY",
                    confidence="MEDIUM",
                    reason=f"Short position, sell order close to current price - likely adding to position"
                )
        else:
            # Order price is above current for longs or below current for shorts
            return OrderAnalysis(
                coin=order.coin,
                order=order,
                position=position,
                analysis_type="ENTRY",
                confidence="LOW",
                reason=f"Order price opposite to expected DCA direction - unusual entry strategy"
            )


async def analyze_wallet(session, wallet) -> Dict[str, List[OrderAnalysis]]:
    print(f"\n🔍 Analyzing wallet: {wallet}")

    # Fetch both positions and orders
    positions_data = await fetch_positions(session, wallet)
    orders_data = await fetch_open_orders(session, wallet)

    if not positions_data and not orders_data:
        print(f"  ❌ No data available for wallet")
        return {}

    positions = parse_positions(positions_data)
    orders = parse_orders(orders_data)

    print(f"  📊 Found {len(positions)} positions and {len(orders)} orders")

    # Display positions
    if positions:
        print("  💼 Current Positions:")
        for coin, pos in positions.items():
            direction = "Long" if pos.size > 0 else "Short"
            pnl_emoji = "📈" if pos.unrealized_pnl > 0 else "📉" if pos.unrealized_pnl < 0 else "➖"
            print(f"    {coin}: {direction} {abs(pos.size):.4f} @ ${pos.entry_price:.2f} | "
                  f"Value: ${pos.current_value:.2f} | PnL: ${pos.unrealized_pnl:.2f} {pnl_emoji}")

    # Analyze orders
    analyses = {}
    if orders:
        print("  📋 Order Analysis:")
        for order in orders:
            position = positions.get(order.coin)
            analysis = analyze_order(order, position)

            if order.coin not in analyses:
                analyses[order.coin] = []
            analyses[order.coin].append(analysis)

            # Display analysis
            emoji_map = {"TP": "🎯", "SL": "🛡️", "ENTRY": "🚀", "DCA": "📈", "UNKNOWN": "❓"}
            confidence_emoji = {"HIGH": "✅", "MEDIUM": "⚠️", "LOW": "❌"}

            print(f"    {emoji_map.get(analysis.analysis_type, '❓')} {order.coin} "
                  f"{analysis.analysis_type} {confidence_emoji.get(analysis.confidence, '❓')}")
            print(f"      Order: {'Buy' if order.side == 'B' else 'Sell'} {order.size:.4f} @ ${order.price:.2f}")
            print(f"      Reason: {analysis.reason}")

    return analyses


async def generate_summary(all_analyses: Dict[str, Dict[str, List[OrderAnalysis]]]):
    print("\n" + "=" * 60)
    print("📊 GLOBAL SUMMARY")
    print("=" * 60)

    # Count order types across all wallets
    total_counts = Counter()
    coin_analysis = defaultdict(lambda: Counter())

    for wallet, wallet_analyses in all_analyses.items():
        for coin, analyses in wallet_analyses.items():
            for analysis in analyses:
                total_counts[analysis.analysis_type] += 1
                coin_analysis[coin][analysis.analysis_type] += 1

    print("🎯 Order Type Distribution:")
    for order_type, count in total_counts.most_common():
        emoji_map = {"TP": "🎯", "SL": "🛡️", "ENTRY": "🚀", "DCA": "📈", "UNKNOWN": "❓"}
        print(f"  {emoji_map.get(order_type, '❓')} {order_type}: {count} orders")

    print("\n💰 By Coin:")
    for coin in TARGET_COINS:
        if coin in coin_analysis:
            print(f"  {coin}:")
            for order_type, count in coin_analysis[coin].most_common():
                emoji_map = {"TP": "🎯", "SL": "🛡️", "ENTRY": "🚀", "DCA": "📈", "UNKNOWN": "❓"}
                print(f"    {emoji_map.get(order_type, '❓')} {order_type}: {count}")

    print("=" * 60)


async def main():
    wallets = load_wallets()
    print(f"🚀 Starting analysis of {len(wallets)} wallets")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                all_analyses = {}

                for wallet in wallets:
                    analyses = await analyze_wallet(session, wallet)
                    if analyses:
                        all_analyses[wallet] = analyses
                    await asyncio.sleep(RATE_LIMIT_DELAY)

                await generate_summary(all_analyses)

            except Exception as e:
                print(f"🔴 Critical error: {e}")

            print(f"\n⏳ Waiting {LOOP_DELAY}s before next analysis round...")
            await asyncio.sleep(LOOP_DELAY)


if __name__ == "__main__":
    asyncio.run(main())