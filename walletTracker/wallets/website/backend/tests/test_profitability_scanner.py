"""
Tests for profitability scanner calculations
"""
import pytest
from datetime import datetime
from scripts.profitabilityScanner import ProfitabilityScanner


class TestDrawdownCalculation:
    """Test maximum drawdown calculation"""

    @pytest.fixture
    def scanner(self):
        """Create scanner instance for testing"""
        # We don't need real MongoDB for testing _calculate_drawdown
        # Pass None as mongo_uri since we're only testing the calculation
        scanner = ProfitabilityScanner.__new__(ProfitabilityScanner)
        return scanner

    def test_drawdown_with_only_profits(self, scanner):
        """Test when all trades are profitable (no drawdown)"""
        fills = [
            {"time": 1000, "closedPnl": "100"},  # +100
            {"time": 2000, "closedPnl": "50"},  # +50
            {"time": 3000, "closedPnl": "75"},  # +75
        ]
        # Cumulative: 100, 150, 225 (only going up)
        # No drawdown should occur

        result = scanner._calculate_drawdown(fills)
        assert result == 0.0

    def test_drawdown_with_losses(self, scanner):
        """Test drawdown calculation with peak and trough"""
        fills = [
            {"time": 1000, "closedPnl": "500"},  # Peak at 500
            {"time": 2000, "closedPnl": "-300"},  # Drop to 200
            {"time": 3000, "closedPnl": "100"},  # Recover to 300
        ]
        # Cumulative: 500 (peak), 200 (trough), 300
        # Drawdown: (500 - 200) / 500 * 100 = 60%

        result = scanner._calculate_drawdown(fills)
        assert result == pytest.approx(60.0, rel=0.01)

    def test_drawdown_empty_fills(self, scanner):
        """Edge case: no trades"""
        fills = []
        result = scanner._calculate_drawdown(fills)
        assert result == 0.0

    def test_drawdown_single_losing_trade(self, scanner):
        """Edge case: only one trade, losing"""
        fills = [
            {"time": 1000, "closedPnl": "-100"}
        ]
        # Peak at -100, stays at -100
        # No meaningful drawdown from negative start

        result = scanner._calculate_drawdown(fills)
        assert result == 0.0

    def test_drawdown_multiple_peaks(self, scanner):
        """Test with multiple peaks - should track maximum drawdown"""
        fills = [
            {"time": 1000, "closedPnl": "300"},  # Peak 1: 300
            {"time": 2000, "closedPnl": "-100"},  # Trough: 200 (33% DD)
            {"time": 3000, "closedPnl": "300"},  # Peak 2: 500
            {"time": 4000, "closedPnl": "-250"},  # Trough: 250 (50% DD) ← MAX
        ]
        # Max drawdown: (500 - 250) / 500 = 50%

        result = scanner._calculate_drawdown(fills)
        assert result == pytest.approx(50.0, rel=0.01)

    def test_drawdown_unsorted_fills(self, scanner):
        """Test that fills are sorted by time correctly"""
        fills = [
            {"time": 3000, "closedPnl": "100"},  # Out of order
            {"time": 1000, "closedPnl": "500"},  # Should be first
            {"time": 2000, "closedPnl": "-300"},  # Middle
        ]
        # After sorting: 500, 200, 300
        # Drawdown: 60%

        result = scanner._calculate_drawdown(fills)
        assert result == pytest.approx(60.0, rel=0.01)


class TestWinRateCalculation:
    """Test win rate calculation logic"""

    def test_win_rate_all_winners(self):
        """Test 100% win rate"""
        fills = [
            {"closedPnl": "100"},
            {"closedPnl": "50"},
            {"closedPnl": "25"},
        ]

        winning_trades = sum(1 for f in fills if float(f.get('closedPnl', 0)) > 0)
        total_trades = len(fills)
        win_rate = (winning_trades / total_trades * 100)

        assert win_rate == 100.0
        assert winning_trades == 3

    def test_win_rate_mixed(self):
        """Test 60% win rate"""
        fills = [
            {"closedPnl": "100"},  # Win
            {"closedPnl": "-50"},  # Loss
            {"closedPnl": "75"},  # Win
            {"closedPnl": "25"},  # Win
            {"closedPnl": "-100"},  # Loss
        ]

        winning_trades = sum(1 for f in fills if float(f.get('closedPnl', 0)) > 0)
        losing_trades = sum(1 for f in fills if float(f.get('closedPnl', 0)) < 0)
        total_trades = len(fills)
        win_rate = (winning_trades / total_trades * 100)

        assert win_rate == 60.0
        assert winning_trades == 3
        assert losing_trades == 2

    def test_win_rate_all_losers(self):
        """Test 0% win rate"""
        fills = [
            {"closedPnl": "-100"},
            {"closedPnl": "-50"},
            {"closedPnl": "-25"},
        ]

        winning_trades = sum(1 for f in fills if float(f.get('closedPnl', 0)) > 0)
        total_trades = len(fills)
        win_rate = (winning_trades / total_trades * 100)

        assert win_rate == 0.0
        assert winning_trades == 0

    def test_win_rate_breakeven_trades_not_counted(self):
        """Test that breakeven trades (PnL = 0) don't count as wins"""
        fills = [
            {"closedPnl": "100"},  # Win
            {"closedPnl": "0"},  # Breakeven (not a win)
            {"closedPnl": "-50"},  # Loss
        ]

        winning_trades = sum(1 for f in fills if float(f.get('closedPnl', 0)) > 0)
        total_trades = len(fills)
        win_rate = (winning_trades / total_trades * 100)

        assert win_rate == pytest.approx(33.33, rel=0.01)
        assert winning_trades == 1

    def test_win_rate_no_trades(self):
        """Edge case: no trades"""
        fills = []

        total_trades = len(fills)
        win_rate = 0 if total_trades == 0 else (0 / total_trades * 100)

        assert win_rate == 0


class TestVolumeCalculation:
    """Test trading volume calculation"""

    def test_total_volume_calculation(self):
        """Test total volume is calculated correctly"""
        fills = [
            {"px": "3000", "sz": "1.5"},  # 3000 * 1.5 = 4500
            {"px": "50000", "sz": "-0.1"},  # 50000 * 0.1 = 5000 (abs)
            {"px": "100", "sz": "10"},  # 100 * 10 = 1000
        ]

        total_volume = sum(
            float(f.get('px', 0)) * abs(float(f.get('sz', 0)))
            for f in fills
        )

        assert total_volume == 10500.0

    def test_average_trade_size(self):
        """Test average trade size calculation"""
        fills = [
            {"px": "1000", "sz": "1"},  # 1000
            {"px": "2000", "sz": "1"},  # 2000
            {"px": "3000", "sz": "1"},  # 3000
        ]

        total_volume = sum(
            float(f.get('px', 0)) * abs(float(f.get('sz', 0)))
            for f in fills
        )
        total_trades = len(fills)
        avg_trade_size = total_volume / total_trades

        assert avg_trade_size == 2000.0
