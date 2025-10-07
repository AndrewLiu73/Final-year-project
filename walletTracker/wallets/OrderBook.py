import requests
import json
import time
from typing import List, Dict, Any
from datetime import datetime


class HyperliquidOrderbookScanner:
    def __init__(self):
        self.base_url = "https://api.hyperliquid.xyz"
        self.info_url = f"{self.base_url}/info"

    def load_trader_wallets(self, filename: str = "goodTraders.txt") -> List[str]:
        """Load wallet addresses from file"""
        try:
            with open(filename, 'r') as f:
                wallets = [line.strip() for line in f if line.strip()]
            print(f"Loaded {len(wallets)} wallet addresses")
            return wallets
        except FileNotFoundError:
            print(f"Error: {filename} not found. Please create the file with wallet addresses.")
            return []
        except Exception as e:
            print(f"Error loading wallets: {e}")
            return []

    def get_open_orders(self, wallet_address: str) -> List[Dict[str, Any]]:
        """Get open orders for a specific wallet"""
        try:
            payload = {
                "type": "openOrders",
                "user": wallet_address
            }

            response = requests.post(self.info_url, json=payload)
            response.raise_for_status()

            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching orders for {wallet_address}: {e}")
            return []

    def get_user_state(self, wallet_address: str) -> Dict[str, Any]:
        """Get user state to determine current positions"""
        try:
            payload = {
                "type": "clearinghouseState",
                "user": wallet_address
            }

            response = requests.post(self.info_url, json=payload)
            response.raise_for_status()

            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching user state for {wallet_address}: {e}")
            return {}

    def is_entry_order(self, order: Dict[str, Any], user_state: Dict[str, Any]) -> bool:
        """Determine if an order is an entry position (not closing existing position)"""
        coin = order.get('coin', '')
        order_side = order.get('side', '')
        order_sz = float(order.get('sz', 0))

        # Get current position for this coin
        current_position = 0
        if 'assetPositions' in user_state:
            for position in user_state['assetPositions']:
                if position.get('position', {}).get('coin') == coin:
                    position_sz = float(position.get('position', {}).get('szi', 0))
                    current_position = position_sz
                    break

        # If no current position, any order is an entry
        if current_position == 0:
            return True

        # If current position exists, check if order is in same direction (adding to position)
        # or opposite direction but smaller than position (partial close)
        if current_position > 0:  # Long position
            if order_side == 'B':  # Buy order - adding to long
                return True
            elif order_side == 'A' and order_sz < abs(current_position):  # Partial close
                return False
            else:  # Full close or flip
                return order_sz > abs(current_position)
        else:  # Short position
            if order_side == 'A':  # Sell order - adding to short
                return True
            elif order_side == 'B' and order_sz < abs(current_position):  # Partial close
                return False
            else:  # Full close or flip
                return order_sz > abs(current_position)

    def format_order_info(self, order: Dict[str, Any], wallet: str) -> Dict[str, Any]:
        """Format order information for display"""
        return {
            'wallet': wallet,
            'coin': order.get('coin', ''),
            'side': 'BUY' if order.get('side') == 'B' else 'SELL',
            'size': float(order.get('sz', 0)),
            'price': float(order.get('limitPx', 0)),
            'order_id': order.get('oid', ''),
            'timestamp': order.get('timestamp', ''),
            'reduce_only': order.get('reduceOnly', False),
            'order_type': order.get('orderType', '')
        }

    def generate_orderbook(self, wallets: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Generate orderbook for all entry orders from tracked wallets"""
        orderbook = {
            'buy_orders': [],
            'sell_orders': []
        }

        print(f"Scanning {len(wallets)} wallets for entry orders...")

        for i, wallet in enumerate(wallets, 1):
            print(f"Processing wallet {i}/{len(wallets)}: {wallet[:8]}...")

            # Get open orders and user state
            open_orders = self.get_open_orders(wallet)
            user_state = self.get_user_state(wallet)

            if not open_orders:
                continue

            # Filter for entry orders only
            for order in open_orders:
                if self.is_entry_order(order, user_state):
                    formatted_order = self.format_order_info(order, wallet)

                    if formatted_order['side'] == 'BUY':
                        orderbook['buy_orders'].append(formatted_order)
                    else:
                        orderbook['sell_orders'].append(formatted_order)

            # Rate limiting
            time.sleep(0.1)

        # Sort orders by price
        orderbook['buy_orders'].sort(key=lambda x: x['price'], reverse=True)  # Highest first
        orderbook['sell_orders'].sort(key=lambda x: x['price'])  # Lowest first

        return orderbook

    def aggregate_orders_by_price_ranges(self, orders: List[Dict[str, Any]], tick_size: float = 0.01) -> Dict[
        float, Dict[str, Any]]:
        """Aggregate orders by price ranges (similar to exchange orderbook)"""
        aggregated = {}

        for order in orders:
            # Round price to tick size
            price_level = round(order['price'] / tick_size) * tick_size

            if price_level not in aggregated:
                aggregated[price_level] = {
                    'total_size': 0,
                    'order_count': 0,
                    'wallets': set(),
                    'coins': set()
                }

            aggregated[price_level]['total_size'] += order['size']
            aggregated[price_level]['order_count'] += 1
            aggregated[price_level]['wallets'].add(order['wallet'][:8])
            aggregated[price_level]['coins'].add(order['coin'])

        return aggregated

    def get_market_prices(self) -> Dict[str, float]:
        """Get current market prices for reference"""
        try:
            payload = {"type": "allMids"}
            response = requests.post(self.info_url, json=payload)
            response.raise_for_status()
            return response.json()
        except:
            return {}

    def display_orderbook(self, orderbook: Dict[str, List[Dict[str, Any]]]):
        """Display the orderbook in exchange style format"""
        print("\n" + "█" * 100)
        print("🔥 HYPERLIQUID TRADERS ORDERBOOK 🔥".center(100))
        print("█" * 100)
        print(
            f"📊 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total Orders: {len(orderbook['buy_orders']) + len(orderbook['sell_orders'])}")

        # Get unique coins
        all_coins = set()
        for order in orderbook['buy_orders'] + orderbook['sell_orders']:
            all_coins.add(order['coin'])

        # Display orderbook for each coin
        for coin in sorted(all_coins):
            self.display_coin_orderbook(coin, orderbook)

    def display_coin_orderbook(self, coin: str, orderbook: Dict[str, List[Dict[str, Any]]], depth: int = 15):
        """Display exchange-style orderbook for a specific coin"""
        # Filter orders for this coin
        buy_orders = [o for o in orderbook['buy_orders'] if o['coin'] == coin]
        sell_orders = [o for o in orderbook['sell_orders'] if o['coin'] == coin]

        if not buy_orders and not sell_orders:
            return

        print(f"\n{'=' * 100}")
        print(f"📈 {coin} ORDERBOOK".center(100))
        print(f"{'=' * 100}")

        # Aggregate orders by price levels
        buy_aggregated = self.aggregate_orders_by_price_ranges(buy_orders)
        sell_aggregated = self.aggregate_orders_by_price_ranges(sell_orders)

        # Get price levels
        buy_levels = sorted(buy_aggregated.keys(), reverse=True)[:depth]
        sell_levels = sorted(sell_aggregated.keys())[:depth]

        # Calculate cumulative sizes
        buy_cumulative = 0
        sell_cumulative = 0

        # Header
        print(f"{'PRICE':<12} {'SIZE':<15} {'CUMULATIVE':<15} {'ORDERS':<8} {'WALLETS':<10} {'SIDE':<6}")
        print("─" * 100)

        # Display sell orders (asks) - from lowest to highest
        for price in reversed(sell_levels):
            data = sell_aggregated[price]
            sell_cumulative += data['total_size']
            size_bar = self.create_size_bar(data['total_size'],
                                            max([d['total_size'] for d in sell_aggregated.values()]), '🔴')
            print(f"{price:<12.4f} {data['total_size']:<15.4f} {sell_cumulative:<15.4f} "
                  f"{data['order_count']:<8} {len(data['wallets']):<10} {'SELL':<6} {size_bar}")

        # Spread calculation
        if buy_levels and sell_levels:
            best_bid = max(buy_levels)
            best_ask = min(sell_levels)
            spread = best_ask - best_bid
            spread_pct = (spread / best_ask) * 100 if best_ask > 0 else 0
            print("─" * 100)
            print(f"💰 SPREAD: {spread:.4f} ({spread_pct:.2f}%) | BID: {best_bid:.4f} | ASK: {best_ask:.4f}".center(100))
            print("─" * 100)
        else:
            print("─" * 100)
            print("💰 NO SPREAD DATA AVAILABLE".center(100))
            print("─" * 100)

        # Reset cumulative for buys
        buy_cumulative = 0

        # Display buy orders (bids) - from highest to lowest
        for price in buy_levels:
            data = buy_aggregated[price]
            buy_cumulative += data['total_size']
            size_bar = self.create_size_bar(data['total_size'], max([d['total_size'] for d in
                                                                     buy_aggregated.values()]) if buy_aggregated else 1,
                                            '🟢')
            print(f"{price:<12.4f} {data['total_size']:<15.4f} {buy_cumulative:<15.4f} "
                  f"{data['order_count']:<8} {len(data['wallets']):<10} {'BUY':<6} {size_bar}")

        # Summary
        total_buy_size = sum(data['total_size'] for data in buy_aggregated.values())
        total_sell_size = sum(data['total_size'] for data in sell_aggregated.values())
        total_buy_orders = sum(data['order_count'] for data in buy_aggregated.values())
        total_sell_orders = sum(data['order_count'] for data in sell_aggregated.values())

        print("─" * 100)
        print(
            f"📊 SUMMARY: BUY {total_buy_size:.2f} ({total_buy_orders} orders) | SELL {total_sell_size:.2f} ({total_sell_orders} orders)")

    def create_size_bar(self, size: float, max_size: float, symbol: str = "█", max_width: int = 20) -> str:
        """Create a visual size bar for orderbook display"""
        if max_size == 0:
            return ""

        bar_length = int((size / max_size) * max_width)
        return symbol * bar_length

    def display_summary_stats(self, orderbook: Dict[str, List[Dict[str, Any]]]):
        """Display overall market summary statistics"""
        all_orders = orderbook['buy_orders'] + orderbook['sell_orders']

        if not all_orders:
            return

        # Get statistics
        total_volume = sum(order['size'] * order['price'] for order in all_orders)
        unique_wallets = len(set(order['wallet'] for order in all_orders))
        unique_coins = len(set(order['coin'] for order in all_orders))

        # Coin distribution
        coin_dist = {}
        for order in all_orders:
            coin = order['coin']
            if coin not in coin_dist:
                coin_dist[coin] = {'count': 0, 'volume': 0}
            coin_dist[coin]['count'] += 1
            coin_dist[coin]['volume'] += order['size'] * order['price']

        print(f"\n{'🎯 MARKET OVERVIEW':<100}")
        print("█" * 100)
        print(f"💎 Total Volume: ${total_volume:,.2f}")
        print(f"👥 Active Wallets: {unique_wallets}")
        print(f"🪙 Trading Pairs: {unique_coins}")
        print(f"📋 Total Orders: {len(all_orders)}")

        print(f"\n🏆 TOP COINS BY ORDER COUNT:")
        for coin, data in sorted(coin_dist.items(), key=lambda x: x[1]['count'], reverse=True)[:5]:
            print(f"   {coin}: {data['count']} orders (${data['volume']:,.2f} volume)")
        print("█" * 100)

    def save_orderbook(self, orderbook: Dict[str, List[Dict[str, Any]]], filename: str = None):
        """Save orderbook to JSON file"""
        if filename is None:
            filename = f"hyperliquid_orderbook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        try:
            with open(filename, 'w') as f:
                json.dump(orderbook, f, indent=2, default=str)
            print(f"\nOrderbook saved to: {filename}")
        except Exception as e:
            print(f"Error saving orderbook: {e}")


def main():
    # Create scanner instance
    scanner = HyperliquidOrderbookScanner()

    # Load wallet addresses
    wallets = scanner.load_trader_wallets("goodTraders.txt")

    if not wallets:
        print("No wallets to scan. Please add wallet addresses to goodTraders.txt")
        return

    # Generate orderbook
    print("Starting orderbook generation...")
    orderbook = scanner.generate_orderbook(wallets)

    # Display results
    scanner.display_orderbook(orderbook)
    scanner.display_summary_stats(orderbook)

    # Save to file
    scanner.save_orderbook(orderbook)

    print(f"\nScan complete! Found {len(orderbook['buy_orders']) + len(orderbook['sell_orders'])} entry orders.")


if __name__ == "__main__":
    main()