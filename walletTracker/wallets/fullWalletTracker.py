from __future__ import annotations
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from hyperliquid.info import Info
from hyperliquid.utils import constants
import logging
import pandas as pd
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, asdict
import numpy as np
from pathlib import Path
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hyperliquid_pnl.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class PnLConfig:
    """Configuration class for PnL analysis"""
    trader_address: str
    start_date: datetime
    end_date: datetime
    initial_window: timedelta = timedelta(days=30)
    max_trades: int = 2000
    max_window: timedelta = timedelta(days=600)
    min_window: timedelta = timedelta(days=1)
    max_retries: int = 5
    save_data: bool = True
    output_dir: str = "pnl_data"


@dataclass
class TradeMetrics:
    """Trade performance metrics"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    max_profit: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float
    total_volume: float
    volume_to_profit_ratio: float
    account_value: float
    squared_volume_profit_ratio: float  # New field for (Volume/Profit)²


class HyperliquidPnLAnalyzer:
    """Enhanced PnL analyzer for Hyperliquid trading data"""

    def __init__(self, config: PnLConfig):
        self.config = config
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.fills_cache = []
        self._ensure_output_dir()

    def _ensure_output_dir(self):
        """Create output directory if it doesn't exist"""
        Path(self.config.output_dir).mkdir(exist_ok=True)

    def fetch_account_value(self) -> float:
        """Fetch current account value"""
        try:
            user_state = self.info.user_state(self.config.trader_address)

            if user_state and 'marginSummary' in user_state:
                account_value = float(user_state['marginSummary']['accountValue'])
                logger.info(f"Current account value: ${account_value:,.2f}")
                return account_value
            else:
                logger.warning("Could not retrieve account value")
                return 0.0

        except Exception as e:
            logger.error(f"Error fetching account value: {e}")
            return 0.0

    def fetch_fills_with_adaptive_window(self) -> List[Dict[str, Any]]:
        """Fetch user fills with adaptive window sizing and comprehensive error handling"""
        window = self.config.initial_window
        window_start = self.config.start_date
        all_fills = []
        retry_count = 0

        logger.info(f"Starting fill retrieval for trader {self.config.trader_address[:10]}...")
        logger.info(f"Date range: {self.config.start_date:%Y-%m-%d} to {self.config.end_date:%Y-%m-%d}")

        while window_start < self.config.end_date:
            window_end = min(window_start + window, self.config.end_date)
            start_ms = int(window_start.timestamp() * 1000)
            end_ms = int(window_end.timestamp() * 1000)

            logger.info(
                f"Fetching fills: {window_start:%Y-%m-%d} to {window_end:%Y-%m-%d} (Window: {window.days} days)")

            try:
                batch = self.info.user_fills_by_time(
                    self.config.trader_address,
                    start_time=start_ms,
                    end_time=end_ms
                )
                time.sleep(0.1)

            except Exception as e:
                logger.error(f"API error fetching fills: {e}")
                if "rate limit" in str(e).lower():
                    logger.warning("Rate limited, waiting 5 seconds...")
                    time.sleep(5)
                    continue
                else:
                    logger.error(f"Skipping window due to error: {e}")
                    window_start = window_end
                    continue

            # Adaptive window logic
            if len(batch) >= self.config.max_trades:
                logger.warning(f"Got {len(batch)} fills (>={self.config.max_trades}), shrinking window...")
                if window > timedelta(days=30):
                    window = timedelta(days=15)
                    logger.warning("Large window detected, force-reset to 15 days")
                else:
                    window = max(window / 2, self.config.min_window)

                retry_count += 1
                if retry_count >= self.config.max_retries:
                    logger.error(f"Max retries exceeded, skipping ahead from {window_start:%Y-%m-%d}")
                    window_start = window_end
                    window = self.config.initial_window
                    retry_count = 0
                continue

            elif len(batch) == 0:
                logger.warning("No fills found, expanding window by 30 days...")
                if window >= self.config.max_window:
                    logger.error(f"Max window reached, skipping ahead from {window_start:%Y-%m-%d}")
                    window_start = window_end
                    window = self.config.initial_window
                    retry_count = 0
                else:
                    window = min(window + timedelta(days=30), self.config.max_window)
                    retry_count += 1
                    if retry_count >= self.config.max_retries:
                        logger.error(f"Max retries exceeded, skipping ahead from {window_start:%Y-%m-%d}")
                        window_start = window_end
                        window = self.config.initial_window
                        retry_count = 0
                continue

            else:
                all_fills.extend(batch)
                logger.info(f"Retrieved {len(batch)} fills (total: {len(all_fills)})")
                window_start = window_end
                window = self.config.initial_window
                retry_count = 0

        logger.info(f"Fill retrieval complete: {len(all_fills)} total fills")
        return all_fills

    def deduplicate_and_sort_fills(self, fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicates and sort fills by timestamp"""
        logger.info("Deduplicating and sorting fills...")

        fills.sort(key=lambda t: t["time"])

        seen = {}
        for fill in fills:
            key = (fill["time"], fill["coin"], fill["side"], fill["sz"], fill["px"])
            if key not in seen:
                seen[key] = fill

        deduped_fills = list(seen.values())
        logger.info(f"Deduplication complete: {len(fills)} -> {len(deduped_fills)} fills")

        return deduped_fills

    def calculate_trade_metrics(self, fills: List[Dict[str, Any]]) -> TradeMetrics:
        """Calculate comprehensive trading performance metrics including squared ratio"""
        logger.info("Calculating trade metrics...")

        if not fills:
            return TradeMetrics(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        # Extract PnL values
        pnl_values = [float(fill.get("closedPnl", 0.0)) for fill in fills]
        cumulative_pnl = np.cumsum(pnl_values)

        # Calculate total volume traded
        total_volume = 0.0
        for fill in fills:
            size = float(fill.get("sz", 0.0))
            price = float(fill.get("px", 0.0))
            notional = size * price
            total_volume += notional

        # Basic metrics
        total_trades = len([pnl for pnl in pnl_values if pnl != 0])
        winning_trades = len([pnl for pnl in pnl_values if pnl > 0])
        losing_trades = len([pnl for pnl in pnl_values if pnl < 0])

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        total_pnl = sum(pnl_values)

        # Drawdown calculation
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdowns = cumulative_pnl - running_max
        max_drawdown = abs(min(drawdowns)) if len(drawdowns) > 0 else 0
        max_profit = max(cumulative_pnl) if len(cumulative_pnl) > 0 else 0

        # Win/Loss averages
        wins = [pnl for pnl in pnl_values if pnl > 0]
        losses = [pnl for pnl in pnl_values if pnl < 0]

        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 0

        # Profit factor
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0
        profit_factor = (total_wins / total_losses) if total_losses > 0 else float('inf')

        # Sharpe ratio
        if len(pnl_values) > 1:
            returns_std = np.std(pnl_values)
            sharpe_ratio = (np.mean(pnl_values) / returns_std) if returns_std > 0 else 0
        else:
            sharpe_ratio = 0

        # Volume to profit ratio
        volume_to_profit_ratio = (total_volume / total_pnl) if total_pnl > 0 else float('inf')

        # Calculate squared volume-to-profit ratio: (Volume/Profit)²
        squared_volume_profit_ratio = volume_to_profit_ratio ** 2 if volume_to_profit_ratio != float('inf') else float(
            'inf')

        # Fetch current account value
        account_value = self.fetch_account_value()

        return TradeMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            max_drawdown=max_drawdown,
            max_profit=max_profit,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            total_volume=total_volume,
            volume_to_profit_ratio=volume_to_profit_ratio,
            account_value=account_value,
            squared_volume_profit_ratio=squared_volume_profit_ratio
        )

    def build_pnl_series(self, fills: List[Dict[str, Any]]) -> Tuple[List[datetime], List[float], List[float]]:
        """Build cumulative PnL and drawdown series"""
        timestamps = []
        cum_pnl = []
        drawdowns = []
        running_pnl = 0.0
        peak_pnl = 0.0

        for fill in fills:
            pnl = float(fill.get("closedPnl", 0.0))
            running_pnl += pnl
            peak_pnl = max(peak_pnl, running_pnl)

            timestamps.append(datetime.fromtimestamp(fill["time"] / 1000))
            cum_pnl.append(running_pnl)
            drawdowns.append(running_pnl - peak_pnl)

        return timestamps, cum_pnl, drawdowns

    def create_enhanced_plots(self, timestamps: List[datetime], cum_pnl: List[float],
                              drawdowns: List[float], metrics: TradeMetrics):
        """Create comprehensive PnL visualization with squared ratio metrics"""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))

        # Main PnL chart
        ax1.plot(timestamps, cum_pnl, linewidth=2, color='blue', alpha=0.8)
        ax1.set_title(f"Cumulative Realized PnL Since {self.config.start_date:%Y-%m-%d}", fontsize=14,
                      fontweight='bold')
        ax1.set_xlabel("Date")
        ax1.set_ylabel("USD Closed PnL")
        ax1.grid(alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

        if cum_pnl:
            ax1.text(0.02, 0.98, f"Final PnL: ${cum_pnl[-1]:,.2f}",
                     transform=ax1.transAxes, va="top",
                     bbox=dict(facecolor="lightgreen" if cum_pnl[-1] > 0 else "lightcoral", alpha=0.8))

        # Drawdown chart
        ax2.fill_between(timestamps, drawdowns, 0, color='red', alpha=0.3)
        ax2.plot(timestamps, drawdowns, color='red', linewidth=1)
        ax2.set_title("Drawdown Analysis", fontsize=14, fontweight='bold')
        ax2.set_xlabel("Date")
        ax2.set_ylabel("Drawdown (USD)")
        ax2.grid(alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

        # Enhanced metrics table
        ax3.axis('off')
        metrics_data = [
            ["Total Trades", f"{metrics.total_trades:,}"],
            ["Win Rate", f"{metrics.win_rate:.1f}%"],
            ["Total PnL", f"${metrics.total_pnl:,.2f}"],
            ["Total Volume", f"${metrics.total_volume:,.2f}"],
            ["Volume/Profit Ratio", f"{metrics.volume_to_profit_ratio:.2f}x"],
            ["(Volume/Profit)²", f"{metrics.squared_volume_profit_ratio:.2f}"],
            ["Account Value", f"${metrics.account_value:,.2f}"],
            ["Max Drawdown", f"${metrics.max_drawdown:,.2f}"],
            ["Profit Factor", f"{metrics.profit_factor:.2f}"]
        ]

        table = ax3.table(cellText=metrics_data, colLabels=["Metric", "Value"],
                          cellLoc='center', loc='center', bbox=[0, 0, 1, 1])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 2)
        ax3.set_title("Performance Metrics", fontsize=14, fontweight='bold')

        # Ratio comparison chart
        ratios = ['Volume/Profit', '(Volume/Profit)²']
        values = [metrics.volume_to_profit_ratio, metrics.squared_volume_profit_ratio]

        # Cap extremely high values for visualization
        display_values = [min(val, 1000) if val != float('inf') else 1000 for val in values]

        bars = ax4.bar(ratios, display_values, color=['skyblue', 'orange'])
        ax4.set_title("Volume-Profit Ratio Comparison", fontsize=14, fontweight='bold')
        ax4.set_ylabel("Ratio Value")
        ax4.grid(alpha=0.3)

        # Add value labels on bars
        for bar, value in zip(bars, values):
            height = bar.get_height()
            if value == float('inf'):
                label = '∞'
            elif value > 1000:
                label = f'{value:.0f}'
            else:
                label = f'{value:.2f}'
            ax4.text(bar.get_x() + bar.get_width() / 2., height + height * 0.01,
                     label, ha='center', va='bottom')

        plt.tight_layout()

        if self.config.save_data:
            plot_filename = f"{self.config.output_dir}/pnl_analysis_{datetime.now():%Y%m%d_%H%M%S}.png"
            plt.savefig(plot_filename, dpi=300, bbox_inches='tight')
            logger.info(f"Plot saved to: {plot_filename}")

        plt.show()

    def save_data(self, fills: List[Dict[str, Any]], metrics: TradeMetrics):
        """Save analysis data to files"""
        if not self.config.save_data:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        fills_filename = f"{self.config.output_dir}/fills_data_{timestamp}.json"
        with open(fills_filename, 'w') as f:
            json.dump(fills, f, indent=2, default=str)

        metrics_filename = f"{self.config.output_dir}/metrics_{timestamp}.json"
        with open(metrics_filename, 'w') as f:
            json.dump(asdict(metrics), f, indent=2)

        config_filename = f"{self.config.output_dir}/config_{timestamp}.json"
        with open(config_filename, 'w') as f:
            json.dump(asdict(self.config), f, indent=2, default=str)

        logger.info(f"Data saved to {self.config.output_dir}/")

    def print_summary(self, metrics: TradeMetrics):
        """Print analysis summary with squared ratio metrics"""
        print("\n" + "=" * 60)
        print("📊 HYPERLIQUID PnL ANALYSIS SUMMARY")
        print("=" * 60)
        print(f"🎯 Total Trades: {metrics.total_trades:,}")
        print(f"📈 Win Rate: {metrics.win_rate:.1f}%")
        print(f"💰 Total PnL: ${metrics.total_pnl:,.2f}")
        print(f"📊 Total Volume: ${metrics.total_volume:,.2f}")
        print(f"⚡ Volume/Profit Ratio: {metrics.volume_to_profit_ratio:.2f}x")
        print(f"🔥 (Volume/Profit)²: {metrics.squared_volume_profit_ratio:.2f}")
        print(f"🏦 Account Value: ${metrics.account_value:,.2f}")
        print(f"📉 Max Drawdown: ${metrics.max_drawdown:,.2f}")
        print(f"🚀 Max Profit: ${metrics.max_profit:,.2f}")
        print(f"✅ Avg Win: ${metrics.avg_win:.2f}")
        print(f"❌ Avg Loss: ${metrics.avg_loss:.2f}")
        print(f"⚡ Profit Factor: {metrics.profit_factor:.2f}")
        print(f"📊 Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
        print("=" * 60)

    def run_analysis(self) -> Tuple[List[Dict[str, Any]], TradeMetrics]:
        """Run complete PnL analysis"""
        logger.info("Starting comprehensive PnL analysis...")

        try:
            raw_fills = self.fetch_fills_with_adaptive_window()

            if not raw_fills:
                logger.warning("No fills found for the specified period")
                return [], TradeMetrics(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

            processed_fills = self.deduplicate_and_sort_fills(raw_fills)
            metrics = self.calculate_trade_metrics(processed_fills)
            timestamps, cum_pnl, drawdowns = self.build_pnl_series(processed_fills)

            self.create_enhanced_plots(timestamps, cum_pnl, drawdowns, metrics)
            self.save_data(processed_fills, metrics)
            self.print_summary(metrics)

            logger.info("Analysis complete!")
            return processed_fills, metrics

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            raise


def main():
    """Main execution function"""
    config = PnLConfig(
        trader_address="0x531fb7439651469b9bf6300c998b87ad97fcb6dd",
        start_date=datetime(2024, 1, 1),
        end_date=datetime.now(),
        save_data=True
    )

    print("🚀 Starting Hyperliquid PnL Analysis...")
    print(f"📅 Date Range: {config.start_date:%Y-%m-%d} to {config.end_date:%Y-%m-%d}")
    print(f"👤 Trader: {config.trader_address}")
    print("-" * 60)

    analyzer = HyperliquidPnLAnalyzer(config)
    fills, metrics = analyzer.run_analysis()

    return fills, metrics


if __name__ == "__main__":
    main()
