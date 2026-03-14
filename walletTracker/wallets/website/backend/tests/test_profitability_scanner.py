"""
Tests for profitability scanner calculations
"""
import pytest
from unittest.mock import MagicMock, patch
from scripts.profitabilityScanner import ProfitabilityScanner


# ── shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def scanner():
    """Create a scanner instance without connecting to MongoDB"""
    s = ProfitabilityScanner.__new__(ProfitabilityScanner)
    return s


# ── drawdown tests ────────────────────────────────────────────────────────────

class TestDrawdown:

    def test_only_profits_no_drawdown(self, scanner):
        """All trades profitable — drawdown must be zero"""
        fills = [
            {"time": 1000, "closedPnl": "100"},
            {"time": 2000, "closedPnl": "50"},
            {"time": 3000, "closedPnl": "75"},
        ]
        assert scanner._calculateDrawdown(fills) == 0.0

    def test_drawdown_with_loss(self, scanner):
        """Peak 500, trough 200 — drawdown = 60%"""
        fills = [
            {"time": 1000, "closedPnl": "500"},
            {"time": 2000, "closedPnl": "-300"},
            {"time": 3000, "closedPnl": "100"},
        ]
        assert scanner._calculateDrawdown(fills) == pytest.approx(60.0, rel=0.01)

    def test_empty_fills(self, scanner):
        """No fills — drawdown = 0"""
        assert scanner._calculateDrawdown([]) == 0.0

    def test_single_losing_trade(self, scanner):
        """Only one losing trade — never had a positive peak, no drawdown"""
        fills = [{"time": 1000, "closedPnl": "-100"}]
        assert scanner._calculateDrawdown(fills) == 0.0

    def test_multiple_peaks_tracks_maximum(self, scanner):
        """
        Peak 1 = 300, trough = 200 (33% DD)
        Peak 2 = 500, trough = 250 (50% DD) <- max
        """
        fills = [
            {"time": 1000, "closedPnl": "300"},
            {"time": 2000, "closedPnl": "-100"},
            {"time": 3000, "closedPnl": "300"},
            {"time": 4000, "closedPnl": "-250"},
        ]
        assert scanner._calculateDrawdown(fills) == pytest.approx(50.0, rel=0.01)

    def test_unsorted_fills_sorted_by_time(self, scanner):
        """Fills out of order — scanner must sort before calculating"""
        fills = [
            {"time": 3000, "closedPnl": "100"},
            {"time": 1000, "closedPnl": "500"},
            {"time": 2000, "closedPnl": "-300"},
        ]
        # After sort: 500 -> 200 -> 300 => 60% DD
        assert scanner._calculateDrawdown(fills) == pytest.approx(60.0, rel=0.01)

    def test_full_wipeout(self, scanner):
        """Portfolio goes to zero — drawdown = 100%"""
        fills = [
            {"time": 1000, "closedPnl": "1000"},
            {"time": 2000, "closedPnl": "-1000"},
        ]
        assert scanner._calculateDrawdown(fills) == pytest.approx(100.0, rel=0.01)

    def test_recovery_after_drawdown(self, scanner):
        """Drawdown then full recovery — max DD is still captured"""
        fills = [
            {"time": 1000, "closedPnl": "1000"},
            {"time": 2000, "closedPnl": "-500"},   # 50% DD
            {"time": 3000, "closedPnl": "500"},    # recovers to 1000
            {"time": 4000, "closedPnl": "500"},    # new peak 1500
        ]
        assert scanner._calculateDrawdown(fills) == pytest.approx(50.0, rel=0.01)


# ── fee tier tests ────────────────────────────────────────────────────────────

class TestFeeTier:

    def test_base_tier_at_or_above_base_rate(self, scanner):
        """Cross rate at or above base rate = tier 0"""
        feeSchedule = {
            "cross": "0.00045",
            "tiers": {
                "vip": [
                    {"cross": "0.00040"},
                    {"cross": "0.00035"},
                ]
            }
        }
        # exactly at base rate
        assert scanner._getFeeTier(feeSchedule, 0.00045) == 0
        # above base rate
        assert scanner._getFeeTier(feeSchedule, 0.00050) == 0

    def test_vip_tier_1(self, scanner):
        """Cross rate below base but above first VIP threshold"""
        feeSchedule = {
            "cross": "0.00045",
            "tiers": {
                "vip": [
                    {"cross": "0.00040"},
                    {"cross": "0.00035"},
                ]
            }
        }
        assert scanner._getFeeTier(feeSchedule, 0.00042) == 1

    def test_vip_tier_2(self, scanner):
        """Cross rate at second VIP threshold"""
        feeSchedule = {
            "cross": "0.00045",
            "tiers": {
                "vip": [
                    {"cross": "0.00040"},
                    {"cross": "0.00035"},
                ]
            }
        }
        assert scanner._getFeeTier(feeSchedule, 0.00035) == 2

    def test_highest_tier_below_all_thresholds(self, scanner):
        """Cross rate below all thresholds = highest tier"""
        feeSchedule = {
            "cross": "0.00045",
            "tiers": {
                "vip": [
                    {"cross": "0.00040"},
                    {"cross": "0.00035"},
                ]
            }
        }
        assert scanner._getFeeTier(feeSchedule, 0.00010) == 2

    def test_empty_tiers(self, scanner):
        """No VIP tiers defined — everything is tier 0"""
        feeSchedule = {
            "cross": "0.00045",
            "tiers": {"vip": []}
        }
        assert scanner._getFeeTier(feeSchedule, 0.00045) == 0

    def test_malformed_fee_schedule_returns_0(self, scanner):
        """Corrupt data should not crash — returns 0"""
        assert scanner._getFeeTier({}, "not_a_number") == 0
        assert scanner._getFeeTier(None, 0.00045) == 0


# ── win rate logic ────────────────────────────────────────────────────────────

class TestWinRate:
    """
    Win rate is computed inline in calculate_profitability.
    These tests verify the logic independently.
    """

    def _compute(self, fills):
        closing = [f for f in fills if float(f.get("closedPnl", 0)) != 0]
        total   = len(closing)
        wins    = sum(1 for f in closing if float(f["closedPnl"]) > 0)
        losses  = sum(1 for f in closing if float(f["closedPnl"]) < 0)
        rate    = (wins / total * 100) if total > 0 else 0
        return wins, losses, total, rate

    def test_all_winners(self):
        fills = [{"closedPnl": "100"}, {"closedPnl": "50"}, {"closedPnl": "25"}]
        wins, losses, total, rate = self._compute(fills)
        assert rate  == 100.0
        assert wins  == 3
        assert losses == 0

    def test_mixed_60_percent(self):
        fills = [
            {"closedPnl": "100"},
            {"closedPnl": "-50"},
            {"closedPnl": "75"},
            {"closedPnl": "25"},
            {"closedPnl": "-100"},
        ]
        wins, losses, total, rate = self._compute(fills)
        assert rate   == 60.0
        assert wins   == 3
        assert losses == 2

    def test_all_losers(self):
        fills = [{"closedPnl": "-100"}, {"closedPnl": "-50"}]
        wins, losses, total, rate = self._compute(fills)
        assert rate == 0.0
        assert wins == 0

    def test_breakeven_excluded_from_wins(self):
        """closedPnl == 0 is excluded because the scanner filters by != 0"""
        fills = [
            {"closedPnl": "100"},
            {"closedPnl": "0"},    # breakeven — excluded
            {"closedPnl": "-50"},
        ]
        wins, losses, total, rate = self._compute(fills)
        # only 2 closing fills count (100 and -50)
        assert total == 2
        assert rate  == pytest.approx(50.0, rel=0.01)

    def test_no_trades(self):
        wins, losses, total, rate = self._compute([])
        assert rate  == 0
        assert total == 0


# ── bot detection logic ───────────────────────────────────────────────────────

class TestBotDetection:
    """
    isLikelyBot = (userCrossRate == 0.0 or userAddRate < 0)
    Pure maker / rebate earners are flagged as bots.
    """

    def _is_bot(self, cross_rate, add_rate):
        return cross_rate == 0.0 or add_rate < 0

    def test_zero_cross_rate_is_bot(self):
        assert self._is_bot(0.0, 0.0002) is True

    def test_negative_add_rate_is_bot(self):
        """Earns rebates on maker — likely algorithmic"""
        assert self._is_bot(0.00045, -0.0001) is True

    def test_normal_rates_not_bot(self):
        assert self._is_bot(0.00045, 0.0002) is False

    def test_both_zero_is_bot(self):
        assert self._is_bot(0.0, 0.0) is True

