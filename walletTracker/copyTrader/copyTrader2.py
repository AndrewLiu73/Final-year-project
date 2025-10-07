import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
import time
import websocket
import threading
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hyperliquid_copy_trader.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class CopyTradeConfig:
    """Configuration for copy trading bot"""
    # Your trading credentials
    private_key: str
    wallet_address: str  # Your wallet address (required for API agent wallets)

    # Wallets to copy
    target_wallets: List[str]

    # Trading parameters
    copy_percentage: float = 0.1  # Copy 10% of target position size
    max_position_size: float = 1000.0  # Maximum USDC per position
    min_position_size: float = 10.0  # Minimum USDC per position

    # Risk management
    max_drawdown: float = 0.2  # Stop copying if 20% drawdown
    stop_loss_percentage: float = 0.05  # 5% stop loss per trade

    # Filtering
    excluded_coins: Set[str] = None
    only_coins: Set[str] = None  # If set, only copy these coins

    # Timing
    copy_delay: float = 0.5  # Delay in seconds before copying
    position_check_interval: float = 5.0  # Check positions every 5 seconds

    # Testnet
    testnet: bool = False


@dataclass
class TradeSignal:
    """Represents a trade signal from a target wallet"""
    wallet: str
    coin: str
    side: str  # "buy" or "sell"
    size: float
    price: float
    timestamp: datetime
    position_size: float  # Current position size after trade


@dataclass
class CopyTradeStats:
    """Statistics for copy trading performance"""
    total_trades: int = 0
    successful_copies: int = 0
    failed_copies: int = 0
    total_pnl: float = 0.0
    active_positions: int = 0
    max_drawdown: float = 0.0


class HyperliquidCopyTrader:
    """Copy trading bot for Hyperliquid"""

    def __init__(self, config: CopyTradeConfig):
        self.config = config
        self.info = Info(constants.TESTNET_API_URL if config.testnet else constants.MAINNET_API_URL, skip_ws=True)
        self.exchange = Exchange(
            config.private_key,
            constants.TESTNET_API_URL if config.testnet else constants.MAINNET_API_URL,
            account_address=config.wallet_address
        )

        # State tracking
        self.target_positions: Dict[str, Dict[str, float]] = {}  # wallet -> {coin: size}
        self.our_positions: Dict[str, float] = {}  # coin -> size
        self.trade_history: List[TradeSignal] = []
        self.stats = CopyTradeStats()
        self.is_running = False
        self.last_position_check = {}

        # Initialize excluded coins
        if config.excluded_coins is None:
            self.config.excluded_coins = set()

        logger.info(f"Initialized copy trader for {len(config.target_wallets)} target wallets")

    async def start(self):
        """Start the copy trading bot"""
        logger.info("🚀 Starting Hyperliquid Copy Trader...")
        self.is_running = True

        # Initialize current positions
        await self.update_our_positions()
        await self.initialize_target_positions()

        # Start monitoring loop
        await self.monitoring_loop()

    async def stop(self):
        """Stop the copy trading bot"""
        logger.info("⏹️ Stopping copy trader...")
        self.is_running = False

    async def initialize_target_positions(self):
        """Initialize current positions of target wallets"""
        for wallet in self.config.target_wallets:
            try:
                user_state = self.info.user_state(wallet)
                positions = {}

                if user_state and 'assetPositions' in user_state:
                    for position in user_state['assetPositions']:
                        coin = position['position']['coin']
                        size = float(position['position']['szi'])
                        if size != 0:
                            positions[coin] = size

                self.target_positions[wallet] = positions
                self.last_position_check[wallet] = datetime.now()
                logger.info(f"Initialized {wallet[:10]}... with {len(positions)} positions")

            except Exception as e:
                logger.error(f"Error initializing positions for {wallet}: {e}")
                self.target_positions[wallet] = {}

    async def update_our_positions(self):
        """Update our current positions"""
        try:
            user_state = self.info.user_state(self.config.wallet_address)
            positions = {}

            if user_state and 'assetPositions' in user_state:
                for position in user_state['assetPositions']:
                    coin = position['position']['coin']
                    size = float(position['position']['szi'])
                    if size != 0:
                        positions[coin] = size

            self.our_positions = positions
            self.stats.active_positions = len(positions)
            logger.debug(f"Updated our positions: {len(positions)} active")

        except Exception as e:
            logger.error(f"Error updating our positions: {e}")

    async def monitoring_loop(self):
        """Main monitoring loop"""
        while self.is_running:
            try:
                # Check each target wallet for position changes
                for wallet in self.config.target_wallets:
                    await self.check_wallet_changes(wallet)

                # Update our positions periodically
                await self.update_our_positions()

                # Print stats periodically
                if len(self.trade_history) > 0 and len(self.trade_history) % 10 == 0:
                    self.print_stats()

                await asyncio.sleep(self.config.position_check_interval)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(5)

    async def check_wallet_changes(self, wallet: str):
        """Check for position changes in a target wallet"""
        try:
            user_state = self.info.user_state(wallet)
            current_positions = {}

            if user_state and 'assetPositions' in user_state:
                for position in user_state['assetPositions']:
                    coin = position['position']['coin']
                    size = float(position['position']['szi'])
                    if size != 0:
                        current_positions[coin] = size

            # Compare with previous positions
            previous_positions = self.target_positions.get(wallet, {})

            # Find changes
            all_coins = set(current_positions.keys()) | set(previous_positions.keys())

            for coin in all_coins:
                current_size = current_positions.get(coin, 0.0)
                previous_size = previous_positions.get(coin, 0.0)

                if abs(current_size - previous_size) > 0.001:  # Significant change
                    # Determine trade direction and size
                    trade_size = current_size - previous_size
                    side = "buy" if trade_size > 0 else "sell"

                    # Get current price
                    price = await self.get_current_price(coin)

                    signal = TradeSignal(
                        wallet=wallet,
                        coin=coin,
                        side=side,
                        size=abs(trade_size),
                        price=price,
                        timestamp=datetime.now(),
                        position_size=current_size
                    )

                    logger.info(
                        f"📊 Trade detected: {wallet[:10]}... {side.upper()} {trade_size:.4f} {coin} at ${price:.4f}")

                    # Execute copy trade
                    await self.execute_copy_trade(signal)

            # Update stored positions
            self.target_positions[wallet] = current_positions
            self.last_position_check[wallet] = datetime.now()

        except Exception as e:
            logger.error(f"Error checking wallet {wallet}: {e}")

    async def get_current_price(self, coin: str) -> float:
        """Get current price for a coin"""
        try:
            all_mids = self.info.all_mids()
            if coin in all_mids:
                return float(all_mids[coin])
            else:
                logger.warning(f"Price not found for {coin}")
                return 0.0
        except Exception as e:
            logger.error(f"Error getting price for {coin}: {e}")
            return 0.0

    async def execute_copy_trade(self, signal: TradeSignal):
        """Execute a copy trade based on the signal"""
        try:
            # Check if we should copy this trade
            if not self.should_copy_trade(signal):
                return

            # Calculate our trade size
            our_trade_size = self.calculate_copy_size(signal)

            if our_trade_size < self.config.min_position_size / signal.price:
                logger.info(f"⏭️ Skipping {signal.coin}: trade size too small")
                return

            # Add delay to avoid front-running
            await asyncio.sleep(self.config.copy_delay)

            # Execute the trade
            success = await self.place_order(signal.coin, signal.side, our_trade_size, signal.price)

            if success:
                self.stats.successful_copies += 1
                logger.info(f"✅ Successfully copied: {signal.side.upper()} {our_trade_size:.4f} {signal.coin}")
            else:
                self.stats.failed_copies += 1
                logger.error(f"❌ Failed to copy: {signal.side.upper()} {our_trade_size:.4f} {signal.coin}")

            self.stats.total_trades += 1
            self.trade_history.append(signal)

        except Exception as e:
            logger.error(f"Error executing copy trade: {e}")
            self.stats.failed_copies += 1

    def should_copy_trade(self, signal: TradeSignal) -> bool:
        """Determine if we should copy this trade"""
        # Check excluded coins
        if signal.coin in self.config.excluded_coins:
            logger.info(f"⏭️ Skipping {signal.coin}: in excluded list")
            return False

        # Check only coins filter
        if self.config.only_coins and signal.coin not in self.config.only_coins:
            logger.info(f"⏭️ Skipping {signal.coin}: not in only_coins list")
            return False

        # Check max drawdown
        if self.stats.max_drawdown > self.config.max_drawdown:
            logger.warning(f"⚠️ Max drawdown exceeded: {self.stats.max_drawdown:.2%}")
            return False

        return True

    def calculate_copy_size(self, signal: TradeSignal) -> float:
        """Calculate the size of our copy trade"""
        # Base copy size as percentage of signal
        base_size = signal.size * self.config.copy_percentage

        # Apply position size limits
        max_size_coins = self.config.max_position_size / signal.price
        min_size_coins = self.config.min_position_size / signal.price

        copy_size = min(base_size, max_size_coins)
        copy_size = max(copy_size, min_size_coins)

        return copy_size

    async def place_order(self, coin: str, side: str, size: float, reference_price: float) -> bool:
        """Place an order on Hyperliquid"""
        try:
            # Use market order for immediate execution
            is_buy = side.lower() == "buy"

            # Get current mid price for better execution
            current_price = await self.get_current_price(coin)
            if current_price == 0:
                current_price = reference_price

            # Add small slippage for market orders
            slippage = 0.001  # 0.1%
            if is_buy:
                limit_price = current_price * (1 + slippage)
            else:
                limit_price = current_price * (1 - slippage)

            # Place the order
            result = self.exchange.order(
                coin=coin,
                is_buy=is_buy,
                sz=size,
                limit_px=limit_price,
                order_type={"limit": {"tif": "Ioc"}}  # Immediate or Cancel
            )

            if result and result.get('status') == 'ok':
                logger.info(f"Order placed successfully: {result}")
                return True
            else:
                logger.error(f"Order failed: {result}")
                return False

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return False

    def print_stats(self):
        """Print current copy trading statistics"""
        success_rate = (
                    self.stats.successful_copies / self.stats.total_trades * 100) if self.stats.total_trades > 0 else 0

        print("\n" + "=" * 60)
        print("📊 COPY TRADING STATISTICS")
        print("=" * 60)
        print(f"🎯 Total Trades: {self.stats.total_trades}")
        print(f"✅ Successful Copies: {self.stats.successful_copies}")
        print(f"❌ Failed Copies: {self.stats.failed_copies}")
        print(f"📈 Success Rate: {success_rate:.1f}%")
        print(f"💰 Total PnL: ${self.stats.total_pnl:.2f}")
        print(f"📊 Active Positions: {self.stats.active_positions}")
        print(f"📉 Max Drawdown: {self.stats.max_drawdown:.2%}")
        print(f"🎯 Target Wallets: {len(self.config.target_wallets)}")
        print("=" * 60)

    def save_state(self, filename: str = "copy_trader_state.json"):
        """Save current state to file"""
        state = {
            'stats': asdict(self.stats),
            'target_positions': self.target_positions,
            'our_positions': self.our_positions,
            'trade_history': [asdict(trade) for trade in self.trade_history[-100:]],  # Last 100 trades
            'timestamp': datetime.now().isoformat()
        }

        with open(filename, 'w') as f:
            json.dump(state, f, indent=2, default=str)

        logger.info(f"State saved to {filename}")


# Example usage and configuration
async def main():
    """Main function to run the copy trader"""

    # Configuration
    config = CopyTradeConfig(
        private_key="YOUR_PRIVATE_KEY",  # Your API wallet private key
        wallet_address="YOUR_WALLET_ADDRESS",  # Your main wallet address
        target_wallets=[
            "0x531fb7439651469b9bf6300c998b87ad97fcb6dd",  # Example profitable wallet
            # Add more wallets to copy
        ],
        copy_percentage=0.05,  # Copy 5% of target position size
        max_position_size=500.0,  # Max $500 per position
        min_position_size=20.0,  # Min $20 per position
        excluded_coins={"DOGE", "SHIB"},  # Don't copy these coins
        testnet=False  # Set to True for testing
    )

    # Create and start copy trader
    copy_trader = HyperliquidCopyTrader(config)

    try:
        await copy_trader.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal...")
    finally:
        await copy_trader.stop()
        copy_trader.save_state()
        copy_trader.print_stats()


if __name__ == "__main__":
    # Run the copy trader
    asyncio.run(main())
