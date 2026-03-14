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
        logging.FileHandler('../../../hyperliquid_pnl.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class PnLConfig:
    """Configuration class for PnL analysis"""
    traderAddress: str
    startDate: datetime
    endDate: datetime
    initialWindow: timedelta = timedelta(days=30)
    maxTrades: int = 2000
    maxWindow: timedelta = timedelta(days=600)
    minWindow: timedelta = timedelta(days=1)
    maxRetries: int = 5
    saveData: bool = True
    outputDir: str = "../../../pnl_data"


@dataclass
class TradeMetrics:
    """Trade performance metrics"""
    totalTrades: int
    winningTrades: int
    losingTrades: int
    winRate: float
    totalPnl: float
    maxDrawdown: float
    maxProfit: float
    avgWin: float
    avgLoss: float
    profitFactor: float
    sharpeRatio: float
    totalVolume: float
    volumeToProfitRatio: float
    accountValue: float
    squaredVolumeProfitRatio: float  # New field for (Volume/Profit)²


class HyperliquidPnLAnalyzer:
    """Enhanced PnL analyzer for Hyperliquid trading data"""

    def __init__(self, config: PnLConfig):
        self.config = config
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.fills_cache = []
        self._ensureOutputDir()

    def _ensureOutputDir(self):
        """Create output directory if it doesn't exist"""
        Path(self.config.outputDir).mkdir(exist_ok=True)

    def fetchAccountValue(self) -> float:
        """Fetch current account value"""
        try:
            userState = self.info.userState(self.config.traderAddress)

            if userState and 'marginSummary' in userState:
                accountValue = float(userState['marginSummary']['accountValue'])
                logger.info(f"Current account value: ${accountValue:,.2f}")
                return accountValue
            else:
                logger.warning("Could not retrieve account value")
                return 0.0

        except Exception as e:
            logger.error(f"Error fetching account value: {e}")
            return 0.0

    def fetchFillsWithAdaptiveWindow(self) -> List[Dict[str, Any]]:
        """Fetch user fills with adaptive window sizing and comprehensive error handling"""
        window = self.config.initialWindow
        windowStart = self.config.startDate
        allFills = []
        retryCount = 0

        logger.info(f"Starting fill retrieval for trader {self.config.traderAddress[:10]}...")
        logger.info(f"Date range: {self.config.startDate:%Y-%m-%d} to {self.config.endDate:%Y-%m-%d}")

        while windowStart < self.config.endDate:
            windowEnd = min(windowStart + window, self.config.endDate)
            startMs = int(windowStart.timestamp() * 1000)
            endMs = int(windowEnd.timestamp() * 1000)

            logger.info(
                f"Fetching fills: {windowStart:%Y-%m-%d} to {windowEnd:%Y-%m-%d} (Window: {window.days} days)")

            try:
                batch = self.info.user_fills_by_time(
                    self.config.traderAddress,
                    start_time=startMs,
                    end_time=endMs
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
                    windowStart = windowEnd
                    continue

            # Adaptive window logic
            if len(batch) >= self.config.maxTrades:
                logger.warning(f"Got {len(batch)} fills (>={self.config.maxTrades}), shrinking window...")
                if window > timedelta(days=30):
                    window = timedelta(days=15)
                    logger.warning("Large window detected, force-reset to 15 days")
                else:
                    window = max(window / 2, self.config.minWindow)

                retryCount += 1
                if retryCount >= self.config.maxRetries:
                    logger.error(f"Max retries exceeded, skipping ahead from {windowStart:%Y-%m-%d}")
                    windowStart = windowEnd
                    window = self.config.initialWindow
                    retryCount = 0
                continue

            elif len(batch) == 0:
                logger.warning("No fills found, expanding window by 30 days...")
                if window >= self.config.maxWindow:
                    logger.error(f"Max window reached, skipping ahead from {windowStart:%Y-%m-%d}")
                    windowStart = windowEnd
                    window = self.config.initialWindow
                    retryCount = 0
                else:
                    window = min(window + timedelta(days=30), self.config.maxWindow)
                    retryCount += 1
                    if retryCount >= self.config.maxRetries:
                        logger.error(f"Max retries exceeded, skipping ahead from {windowStart:%Y-%m-%d}")
                        windowStart = windowEnd
                        window = self.config.initialWindow
                        retryCount = 0
                continue

            else:
                allFills.extend(batch)
                logger.info(f"Retrieved {len(batch)} fills (total: {len(allFills)})")
                windowStart = windowEnd
                window = self.config.initialWindow
                retryCount = 0

        logger.info(f"Fill retrieval complete: {len(allFills)} total fills")
        return allFills

    def deduplicateAndSortFills(self, fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicates and sort fills by timestamp"""
        logger.info("Deduplicating and sorting fills...")

        fills.sort(key=lambda t: t["time"])

        seen = {}
        for fill in fills:
            key = (fill["time"], fill["coin"], fill["side"], fill["sz"], fill["px"])
            if key not in seen:
                seen[key] = fill

        dedupedFills = list(seen.values())
        logger.info(f"Deduplication complete: {len(fills)} -> {len(dedupedFills)} fills")

        return dedupedFills

    def calculateTradeMetrics(self, fills: List[Dict[str, Any]]) -> TradeMetrics:
        """Calculate comprehensive trading performance metrics including squared ratio"""
        logger.info("Calculating trade metrics...")

        if not fills:
            return TradeMetrics(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        # Extract PnL values
        pnlValues = [float(fill.get("closedPnl", 0.0)) for fill in fills]
        cumulativePnl = np.cumsum(pnlValues)

        # Calculate total volume traded
        totalVolume = 0.0
        for fill in fills:
            size = float(fill.get("sz", 0.0))
            price = float(fill.get("px", 0.0))
            notional = size * price
            totalVolume += notional

        # Basic metrics
        totalTrades = len([pnl for pnl in pnlValues if pnl != 0])
        winningTrades = len([pnl for pnl in pnlValues if pnl > 0])
        losingTrades = len([pnl for pnl in pnlValues if pnl < 0])

        winRate = (winningTrades / totalTrades * 100) if totalTrades > 0 else 0
        totalPnl = sum(pnlValues)

        # Drawdown calculation
        runningMax = np.maximum.accumulate(cumulativePnl)
        drawdowns = cumulativePnl - runningMax
        maxDrawdown = abs(min(drawdowns)) if len(drawdowns) > 0 else 0
        maxProfit = max(cumulativePnl) if len(cumulativePnl) > 0 else 0

        # Win/Loss averages
        wins = [pnl for pnl in pnlValues if pnl > 0]
        losses = [pnl for pnl in pnlValues if pnl < 0]

        avgWin = np.mean(wins) if wins else 0
        avgLoss = abs(np.mean(losses)) if losses else 0

        # Profit factor
        totalWins = sum(wins) if wins else 0
        totalLosses = abs(sum(losses)) if losses else 0
        profitFactor = (totalWins / totalLosses) if totalLosses > 0 else float('inf')

        # Sharpe ratio
        if len(pnlValues) > 1:
            returnsStd = np.std(pnlValues)
            sharpeRatio = (np.mean(pnlValues) / returnsStd) if returnsStd > 0 else 0
        else:
            sharpeRatio = 0

        # Volume to profit ratio
        volumeToProfitRatio = (totalVolume / totalPnl) if totalPnl > 0 else float('inf')

        # Calculate squared volume-to-profit ratio: (Volume/Profit)²
        squaredVolumeProfitRatio = volumeToProfitRatio ** 2 if volumeToProfitRatio != float('inf') else float(
            'inf')

        # Fetch current account value
        accountValue = self.fetchAccountValue()

        return TradeMetrics(
            totalTrades=totalTrades,
            winningTrades=winningTrades,
            losingTrades=losingTrades,
            winRate=winRate,
            totalPnl=totalPnl,
            maxDrawdown=maxDrawdown,
            maxProfit=maxProfit,
            avgWin=avgWin,
            avgLoss=avgLoss,
            profitFactor=profitFactor,
            sharpeRatio=sharpeRatio,
            totalVolume=totalVolume,
            volumeToProfitRatio=volumeToProfitRatio,
            accountValue=accountValue,
            squaredVolumeProfitRatio=squaredVolumeProfitRatio
        )

    def buildPnlSeries(self, fills: List[Dict[str, Any]]) -> Tuple[List[datetime], List[float], List[float]]:
        """Build cumulative PnL and drawdown series"""
        timestamps = []
        cumPnl = []
        drawdowns = []
        runningPnl = 0.0
        peakPnl = 0.0

        for fill in fills:
            pnl = float(fill.get("closedPnl", 0.0))
            runningPnl += pnl
            peakPnl = max(peakPnl, runningPnl)

            timestamps.append(datetime.fromtimestamp(fill["time"] / 1000))
            cumPnl.append(runningPnl)
            drawdowns.append(runningPnl - peakPnl)

        return timestamps, cumPnl, drawdowns

    def createEnhancedPlots(self, timestamps: List[datetime], cumPnl: List[float],
                              drawdowns: List[float], metrics: TradeMetrics):
        """Create comprehensive PnL visualization with squared ratio metrics"""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))

        # Main PnL chart
        ax1.plot(timestamps, cumPnl, linewidth=2, color='blue', alpha=0.8)
        ax1.set_title(f"Cumulative Realized PnL Since {self.config.startDate:%Y-%m-%d}", fontsize=14,
                      fontweight='bold')
        ax1.set_xlabel("Date")
        ax1.set_ylabel("USD Closed PnL")
        ax1.grid(alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

        if cumPnl:
            ax1.text(0.02, 0.98, f"Final PnL: ${cumPnl[-1]:,.2f}",
                     transform=ax1.transAxes, va="top",
                     bbox=dict(facecolor="lightgreen" if cumPnl[-1] > 0 else "lightcoral", alpha=0.8))

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
        metricsData = [
            ["Total Trades", f"{metrics.totalTrades:,}"],
            ["Win Rate", f"{metrics.winRate:.1f}%"],
            ["Total PnL", f"${metrics.totalPnl:,.2f}"],
            ["Total Volume", f"${metrics.totalVolume:,.2f}"],
            ["Volume/Profit Ratio", f"{metrics.volumeToProfitRatio:.2f}x"],
            ["(Volume/Profit)²", f"{metrics.squaredVolumeProfitRatio:.2f}"],
            ["Account Value", f"${metrics.accountValue:,.2f}"],
            ["Max Drawdown", f"${metrics.maxDrawdown:,.2f}"],
            ["Profit Factor", f"{metrics.profitFactor:.2f}"]
        ]

        table = ax3.table(cellText=metricsData, colLabels=["Metric", "Value"],
                          cellLoc='center', loc='center', bbox=[0, 0, 1, 1])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 2)
        ax3.set_title("Performance Metrics", fontsize=14, fontweight='bold')

        # Ratio comparison chart
        ratios = ['Volume/Profit', '(Volume/Profit)²']
        values = [metrics.volumeToProfitRatio, metrics.squaredVolumeProfitRatio]

        # Cap extremely high values for visualization
        displayValues = [min(val, 1000) if val != float('inf') else 1000 for val in values]

        bars = ax4.bar(ratios, displayValues, color=['skyblue', 'orange'])
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

        if self.config.saveData:
            plotFilename = f"{self.config.outputDir}/pnl_analysis_{datetime.now():%Y%m%d_%H%M%S}.png"
            plt.savefig(plotFilename, dpi=300, bbox_inches='tight')
            logger.info(f"Plot saved to: {plotFilename}")

        plt.show()

    def saveData(self, fills: List[Dict[str, Any]], metrics: TradeMetrics):
        """Save analysis data to files"""
        if not self.config.saveData:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        fillsFilename = f"{self.config.outputDir}/fills_data_{timestamp}.json"
        with open(fillsFilename, 'w') as f:
            json.dump(fills, f, indent=2, default=str)

        metricsFilename = f"{self.config.outputDir}/metrics_{timestamp}.json"
        with open(metricsFilename, 'w') as f:
            json.dump(asdict(metrics), f, indent=2)

        configFilename = f"{self.config.outputDir}/config_{timestamp}.json"
        with open(configFilename, 'w') as f:
            json.dump(asdict(self.config), f, indent=2, default=str)

        logger.info(f"Data saved to {self.config.outputDir}/")

    def printSummary(self, metrics: TradeMetrics):
        """Print analysis summary with squared ratio metrics"""
        print("\n" + "=" * 60)
        print("📊 HYPERLIQUID PnL ANALYSIS SUMMARY")
        print("=" * 60)
        print(f"🎯 Total Trades: {metrics.totalTrades:,}")
        print(f"📈 Win Rate: {metrics.winRate:.1f}%")
        print(f"💰 Total PnL: ${metrics.totalPnl:,.2f}")
        print(f"📊 Total Volume: ${metrics.totalVolume:,.2f}")
        print(f"⚡ Volume/Profit Ratio: {metrics.volumeToProfitRatio:.2f}x")
        print(f"🔥 (Volume/Profit)²: {metrics.squaredVolumeProfitRatio:.2f}")
        print(f"🏦 Account Value: ${metrics.accountValue:,.2f}")
        print(f"📉 Max Drawdown: ${metrics.maxDrawdown:,.2f}")
        print(f"🚀 Max Profit: ${metrics.maxProfit:,.2f}")
        print(f"✅ Avg Win: ${metrics.avgWin:.2f}")
        print(f"❌ Avg Loss: ${metrics.avgLoss:.2f}")
        print(f"⚡ Profit Factor: {metrics.profitFactor:.2f}")
        print(f"📊 Sharpe Ratio: {metrics.sharpeRatio:.2f}")
        print("=" * 60)

    def runAnalysis(self) -> Tuple[List[Dict[str, Any]], TradeMetrics]:
        """Run complete PnL analysis"""
        logger.info("Starting comprehensive PnL analysis...")

        try:
            rawFills = self.fetchFillsWithAdaptiveWindow()

            if not rawFills:
                logger.warning("No fills found for the specified period")
                return [], TradeMetrics(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

            processedFills = self.deduplicateAndSortFills(rawFills)
            metrics = self.calculateTradeMetrics(processedFills)
            timestamps, cumPnl, drawdowns = self.buildPnlSeries(processedFills)

            self.createEnhancedPlots(timestamps, cumPnl, drawdowns, metrics)
            self.saveData(processedFills, metrics)
            self.printSummary(metrics)

            logger.info("Analysis complete!")
            return processedFills, metrics

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            raise


def main():
    """Main execution function"""
    config = PnLConfig(
        traderAddress="0x8e096995c3e4a3f0bc5b3ea1cba94de2aa4d70c9",
        startDate=datetime(2024, 1, 1),
        endDate=datetime.now(),
        saveData=True
    )

    print("🚀 Starting Hyperliquid PnL Analysis...")
    print(f"📅 Date Range: {config.startDate:%Y-%m-%d} to {config.endDate:%Y-%m-%d}")
    print(f"👤 Trader: {config.traderAddress}")
    print("-" * 60)

    analyzer = HyperliquidPnLAnalyzer(config)
    fills, metrics = analyzer.runAnalysis()

    return fills, metrics


if __name__ == "__main__":
    main()