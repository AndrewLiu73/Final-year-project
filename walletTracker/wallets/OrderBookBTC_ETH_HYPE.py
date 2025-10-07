import asyncio
import aiohttp
import json
import time
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
import signal
import sys
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
import sqlite3
from contextlib import asynccontextmanager
from enum import Enum
import backoff

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hyperliquid_scanner.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY = "B"
    SELL = "A"


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


@dataclass
class OrderInfo:
    wallet: str
    coin: str
    side: str
    size: float
    price: float
    order_id: str
    timestamp: str
    reduce_only: bool
    order_type: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AggregatedLevel:
    price: float
    total_size: float
    order_count: int
    wallets: Set[str]
    coins: Set[str]


class HyperliquidAPIError(Exception):
    """Base exception for Hyperliquid API errors"""
    pass


class RateLimitError(HyperliquidAPIError):
    """Raised when API rate limit is exceeded"""
    pass


class ConnectionError(HyperliquidAPIError):
    """Raised when connection to API fails"""
    pass


class HyperliquidOrderbookScanner:
    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.base_url = self.config.get("base_url", "https://api.hyperliquid.xyz")
        self.info_url = f"{self.base_url}/info"
        self.target_coins = self.config.get("target_coins", ['BTC', 'ETH', 'HYPE'])
        self.running = True
        self.session: Optional[aiohttp.ClientSession] = None
        self.db_path = self.config.get("db_path", "orderbook_data.db")
        self._init_database()

        # Rate limiting configuration
        self.max_requests_per_second = self.config.get("max_requests_per_second", 10)
        self.request_semaphore = asyncio.Semaphore(self.max_requests_per_second)

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        config_file = Path(config_path)
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")

        # Default configuration
        default_config = {
            "base_url": "https://api.hyperliquid.xyz",
            "target_coins": ["BTC", "ETH", "HYPE"],
            "max_requests_per_second": 10,
            "request_timeout": 10,
            "max_retries": 3,
            "db_path": "orderbook_data.db",
            "scan_interval_hours": 1,
            "orderbook_depth": 10
        }

        # Save default config
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=2)

        return default_config

    def _init_database(self):
        """Initialize SQLite database for storing historical data"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                coin TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                wallet TEXT NOT NULL,
                order_id TEXT NOT NULL,
                UNIQUE(timestamp, order_id)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_timestamp_coin 
            ON orderbook_snapshots(timestamp, coin)
        ''')

        conn.commit()
        conn.close()

    def signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully"""
        logger.info("Stopping scanner...")
        self.running = False
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())
        sys.exit(0)

    async def load_trader_wallets(self, filename: str = "goodTraders.txt") -> List[str]:
        """Load wallet addresses from file asynchronously"""
        try:
            wallet_file = Path(filename)
            if not wallet_file.exists():
                logger.error(f"{filename} not found. Please create the file with wallet addresses.")
                return []

            with open(wallet_file, 'r') as f:
                wallets = [line.strip() for line in f if line.strip()]

            logger.info(f"Loaded {len(wallets)} wallet addresses")
            return wallets
        except Exception as e:
            logger.error(f"Error loading wallets: {e}")
            return []

    @asynccontextmanager
    async def get_session(self):
        """Context manager for HTTP session"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.get("request_timeout", 10))
            connector = aiohttp.TCPConnector(
                limit=100,  # Total connection pool size
                limit_per_host=20,  # Per-host connection limit
                ttl_dns_cache=300,  # DNS cache TTL
                use_dns_cache=True,
            )
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": "HyperliquidScanner/1.0"}
            )

        try:
            yield self.session
        finally:
            pass  # Keep session alive for reuse

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=3,
        max_time=30
    )
    async def _make_api_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make API request with retry logic and rate limiting"""
        async with self.request_semaphore:
            async with self.get_session() as session:
                try:
                    async with session.post(self.info_url, json=payload) as response:
                        if response.status == 429:
                            retry_after = int(response.headers.get('Retry-After', 60))
                            logger.warning(f"Rate limited. Waiting {retry_after} seconds")
                            await asyncio.sleep(retry_after)
                            raise RateLimitError("Rate limit exceeded")

                        response.raise_for_status()
                        return await response.json()

                except aiohttp.ClientError as e:
                    logger.error(f"API request failed: {e}")
                    raise ConnectionError(f"Failed to connect to API: {e}")

    async def get_open_orders(self, wallet_address: str) -> List[Dict[str, Any]]:
        """Get open orders for a specific wallet"""
        try:
            payload = {
                "type": "openOrders",
                "user": wallet_address
            }

            result = await self._make_api_request(payload)
            return result if isinstance(result, list) else []

        except Exception as e:
            logger.error(f"Error fetching orders for {wallet_address[:8]}: {e}")
            return []

    async def get_user_state(self, wallet_address: str) -> Dict[str, Any]:
        """Get user state to determine current positions"""
        try:
            payload = {
                "type": "clearinghouseState",
                "user": wallet_address
            }

            result = await self._make_api_request(payload)
            return result if isinstance(result, dict) else {}

        except Exception as e:
            logger.error(f"Error fetching user state for {wallet_address[:8]}: {e}")
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

        # Check if order is in same direction (adding to position)
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

    def format_order_info(self, order: Dict[str, Any], wallet: str) -> OrderInfo:
        """Format order information into structured data"""
        return OrderInfo(
            wallet=wallet,
            coin=order.get('coin', ''),
            side='BUY' if order.get('side') == 'B' else 'SELL',
            size=float(order.get('sz', 0)),
            price=float(order.get('limitPx', 0)),
            order_id=order.get('oid', ''),
            timestamp=order.get('timestamp', ''),
            reduce_only=order.get('reduceOnly', False),
            order_type=order.get('orderType', '')
        )

    async def process_wallet_batch(self, wallets: List[str]) -> List[OrderInfo]:
        """Process a batch of wallets concurrently"""
        tasks = []
        for wallet in wallets:
            task = self.process_single_wallet(wallet)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results and filter out exceptions
        orders = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Wallet processing failed: {result}")
            elif isinstance(result, list):
                orders.extend(result)

        return orders

    async def process_single_wallet(self, wallet: str) -> List[OrderInfo]:
        """Process a single wallet and return entry orders"""
        try:
            # Fetch data concurrently
            open_orders_task = self.get_open_orders(wallet)
            user_state_task = self.get_user_state(wallet)

            open_orders, user_state = await asyncio.gather(
                open_orders_task, user_state_task
            )

            if not open_orders:
                return []

            # Filter for entry orders and target coins
            entry_orders = []
            for order in open_orders:
                coin = order.get('coin', '')
                if coin in self.target_coins and self.is_entry_order(order, user_state):
                    formatted_order = self.format_order_info(order, wallet)
                    entry_orders.append(formatted_order)

            return entry_orders

        except Exception as e:
            logger.error(f"Error processing wallet {wallet[:8]}: {e}")
            return []

    async def generate_orderbook(self, wallets: List[str]) -> Dict[str, List[OrderInfo]]:
        """Generate orderbook for all entry orders from tracked wallets"""
        logger.info(f"Scanning {len(wallets)} wallets for entry orders in {', '.join(self.target_coins)}")

        # Process wallets in batches to avoid overwhelming the API
        batch_size = 20
        all_orders = []

        for i in range(0, len(wallets), batch_size):
            batch = wallets[i:i + batch_size]
            logger.info(f"Processing batch {i // batch_size + 1}/{(len(wallets) + batch_size - 1) // batch_size}")

            batch_orders = await self.process_wallet_batch(batch)
            all_orders.extend(batch_orders)

            # Rate limiting between batches
            if i + batch_size < len(wallets):
                await asyncio.sleep(1)

        # Separate buy and sell orders
        buy_orders = [order for order in all_orders if order.side == 'BUY']
        sell_orders = [order for order in all_orders if order.side == 'SELL']

        # Sort orders by price
        buy_orders.sort(key=lambda x: x.price, reverse=True)
        sell_orders.sort(key=lambda x: x.price)

        return {
            'buy_orders': buy_orders,
            'sell_orders': sell_orders
        }

    def save_to_database(self, orderbook: Dict[str, List[OrderInfo]]):
        """Save orderbook snapshot to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            timestamp = datetime.now().isoformat()

            for orders in [orderbook['buy_orders'], orderbook['sell_orders']]:
                for order in orders:
                    cursor.execute('''
                        INSERT OR IGNORE INTO orderbook_snapshots 
                        (timestamp, coin, side, price, size, wallet, order_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        timestamp, order.coin, order.side, order.price,
                        order.size, order.wallet, order.order_id
                    ))

            conn.commit()
            conn.close()
            logger.info(f"Saved orderbook snapshot to database")

        except Exception as e:
            logger.error(f"Error saving to database: {e}")

    def aggregate_orders_by_price_ranges(self, orders: List[OrderInfo], tick_size: float = 0.01) -> Dict[
        float, AggregatedLevel]:
        """Aggregate orders by price ranges"""
        aggregated = {}

        for order in orders:
            price_level = round(order.price / tick_size) * tick_size

            if price_level not in aggregated:
                aggregated[price_level] = AggregatedLevel(
                    price=price_level,
                    total_size=0,
                    order_count=0,
                    wallets=set(),
                    coins=set()
                )

            level = aggregated[price_level]
            level.total_size += order.size
            level.order_count += 1
            level.wallets.add(order.wallet[:8])
            level.coins.add(order.coin)

        return aggregated

    def display_orderbook(self, orderbook: Dict[str, List[OrderInfo]]):
        """Display the enhanced orderbook"""
        # Clear screen
        print("\033[2J\033[H")

        print("█" * 100)
        print("🔥 ENHANCED HYPERLIQUID TRADERS ORDERBOOK 🔥".center(100))
        print("█" * 100)

        total_orders = len(orderbook['buy_orders']) + len(orderbook['sell_orders'])
        print(f"📊 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total Orders: {total_orders}")

        # Get available coins
        all_orders = orderbook['buy_orders'] + orderbook['sell_orders']
        available_coins = set(order.coin for order in all_orders)
        coins_to_show = [coin for coin in self.target_coins if coin in available_coins]

        if not coins_to_show:
            print(f"⚠️  No orders found for {', '.join(self.target_coins)}")
            return

        print(f"🎯 Active: {', '.join(coins_to_show)}")

        # Display orderbook for each coin
        for coin in coins_to_show:
            self.display_coin_orderbook(coin, orderbook)

    def display_coin_orderbook(self, coin: str, orderbook: Dict[str, List[OrderInfo]], depth: int = None):
        """Display enhanced orderbook for a specific coin"""
        if depth is None:
            depth = self.config.get("orderbook_depth", 10)

        # Filter orders for this coin
        buy_orders = [o for o in orderbook['buy_orders'] if o.coin == coin]
        sell_orders = [o for o in orderbook['sell_orders'] if o.coin == coin]

        if not buy_orders and not sell_orders:
            return

        print(f"\n{'=' * 100}")
        print(f"📈 {coin} ENHANCED ORDERBOOK".center(100))
        print(f"{'=' * 100}")

        # Aggregate orders
        buy_aggregated = self.aggregate_orders_by_price_ranges(buy_orders)
        sell_aggregated = self.aggregate_orders_by_price_ranges(sell_orders)

        # Get price levels
        buy_levels = sorted(buy_aggregated.keys(), reverse=True)[:depth]
        sell_levels = sorted(sell_aggregated.keys())[:depth]

        # Display with enhanced formatting
        print(f"{'PRICE':<12} {'SIZE':<15} {'CUMULATIVE':<15} {'ORDERS':<8} {'WALLETS':<10} {'SIDE':<6} {'VISUAL':<20}")
        print("─" * 100)

        # Display sell orders (asks)
        sell_cumulative = 0
        max_sell_size = max([level.total_size for level in sell_aggregated.values()]) if sell_aggregated else 1

        for price in reversed(sell_levels):
            level = sell_aggregated[price]
            sell_cumulative += level.total_size
            size_bar = self.create_enhanced_size_bar(level.total_size, max_sell_size, '🔴')
            print(f"{price:<12.4f} {level.total_size:<15.4f} {sell_cumulative:<15.4f} "
                  f"{level.order_count:<8} {len(level.wallets):<10} {'SELL':<6} {size_bar}")

        # Spread calculation
        if buy_levels and sell_levels:
            best_bid = max(buy_levels)
            best_ask = min(sell_levels)
            spread = best_ask - best_bid
            spread_pct = (spread / best_ask) * 100 if best_ask > 0 else 0
            print("─" * 100)
            print(f"💰 SPREAD: {spread:.4f} ({spread_pct:.2f}%) | BID: {best_bid:.4f} | ASK: {best_ask:.4f}".center(100))
            print("─" * 100)

        # Display buy orders (bids)
        buy_cumulative = 0
        max_buy_size = max([level.total_size for level in buy_aggregated.values()]) if buy_aggregated else 1

        for price in buy_levels:
            level = buy_aggregated[price]
            buy_cumulative += level.total_size
            size_bar = self.create_enhanced_size_bar(level.total_size, max_buy_size, '🟢')
            print(f"{price:<12.4f} {level.total_size:<15.4f} {buy_cumulative:<15.4f} "
                  f"{level.order_count:<8} {len(level.wallets):<10} {'BUY':<6} {size_bar}")

    def create_enhanced_size_bar(self, size: float, max_size: float, symbol: str = "█", max_width: int = 20) -> str:
        """Create enhanced visual size bar"""
        if max_size == 0:
            return ""

        bar_length = int((size / max_size) * max_width)
        bar = symbol * bar_length
        percentage = f"({size / max_size * 100:.1f}%)"
        return f"{bar:<{max_width}} {percentage}"

    async def save_orderbook_async(self, orderbook: Dict[str, List[OrderInfo]], filename: str = None):
        """Save orderbook to JSON file asynchronously"""
        if filename is None:
            filename = f"hyperliquid_orderbook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        try:
            # Convert OrderInfo objects to dictionaries
            serializable_orderbook = {
                'buy_orders': [order.to_dict() for order in orderbook['buy_orders']],
                'sell_orders': [order.to_dict() for order in orderbook['sell_orders']],
                'timestamp': datetime.now().isoformat(),
                'total_orders': len(orderbook['buy_orders']) + len(orderbook['sell_orders'])
            }

            with open(filename, 'w') as f:
                json.dump(serializable_orderbook, f, indent=2, default=str)

            logger.info(f"Orderbook saved to: {filename}")
        except Exception as e:
            logger.error(f"Error saving orderbook: {e}")

    async def run_continuous_scan(self, wallets: List[str], scan_interval_hours: int = None):
        """Run continuous orderbook scanning with enhanced error handling"""
        if scan_interval_hours is None:
            scan_interval_hours = self.config.get("scan_interval_hours", 1)

        scan_interval_seconds = scan_interval_hours * 3600

        logger.info(f"Starting continuous orderbook scanner for {', '.join(self.target_coins)}")
        logger.info(f"Scanning every {scan_interval_hours} hour(s)")
        logger.info("Press Ctrl+C to stop")

        scan_count = 0

        while self.running:
            try:
                scan_count += 1
                start_time = time.time()
                logger.info(f"Starting scan #{scan_count} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                # Generate orderbook
                orderbook = await self.generate_orderbook(wallets)

                # Save to database
                self.save_to_database(orderbook)

                # Display results
                self.display_orderbook(orderbook)

                # Save to file
                await self.save_orderbook_async(orderbook)

                scan_time = time.time() - start_time
                total_orders = len(orderbook['buy_orders']) + len(orderbook['sell_orders'])

                logger.info(f"Scan #{scan_count} complete! Found {total_orders} entry orders in {scan_time:.2f}s")

                if self.running:
                    next_scan = datetime.now().timestamp() + scan_interval_seconds
                    next_scan_time = datetime.fromtimestamp(next_scan).strftime('%Y-%m-%d %H:%M:%S')
                    logger.info(f"Next scan at: {next_scan_time}")

                    # Sleep with periodic checks
                    for _ in range(scan_interval_seconds):
                        if not self.running:
                            break
                        await asyncio.sleep(1)

            except KeyboardInterrupt:
                logger.info("Scan interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error during scan: {e}")
                logger.info("Retrying in 5 minutes...")
                await asyncio.sleep(300)

    async def cleanup(self):
        """Cleanup resources"""
        if self.session and not self.session.closed:
            await self.session.close()


async def main():
    """Main async function"""
    scanner = HyperliquidOrderbookScanner()

    # Set up signal handler
    signal.signal(signal.SIGINT, scanner.signal_handler)

    try:
        # Load wallet addresses
        wallets = await scanner.load_trader_wallets("goodTraders.txt")

        if not wallets:
            logger.error("No wallets to scan. Please add wallet addresses to goodTraders.txt")
            return

        logger.info(f"Configured to track: {', '.join(scanner.target_coins)}")

        # Get scan interval from user
        try:
            interval_input = input("Enter scan interval in hours (default: 1): ").strip()
            scan_interval = int(interval_input) if interval_input else 1
            if scan_interval < 1:
                scan_interval = 1
                logger.info("Minimum interval is 1 hour. Using 1 hour interval.")
        except ValueError:
            scan_interval = 1
            logger.info("Invalid input. Using default 1 hour interval.")

        # Start continuous scanning
        await scanner.run_continuous_scan(wallets, scan_interval)

    finally:
        await scanner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
