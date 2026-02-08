"""Unit tests for CostPool — supports both long and short positions."""

import pytest
from src.cost_pool import CostPool


class TestLongPosition:
    """Standard buy-then-sell (long) operations."""

    def test_single_buy(self):
        pool = CostPool("TEST")
        pool.buy(100, 1000)
        assert pool.quantity == 100
        assert pool.total_cost == 1000
        assert pool.avg_cost == 10

    def test_two_buys_weighted_average(self):
        pool = CostPool("TEST")
        pool.buy(100, 1000)
        pool.buy(100, 2000)
        assert pool.quantity == 200
        assert pool.total_cost == 3000
        assert pool.avg_cost == 15

    def test_buy_then_sell(self):
        pool = CostPool("TEST")
        pool.buy(100, 1000)
        cost_basis = pool.sell(50, settled_amount=600)  # settled_amount ignored for long close
        assert cost_basis == 500  # 50 * 10
        assert pool.quantity == 50
        assert pool.avg_cost == 10

    def test_sell_all(self):
        pool = CostPool("TEST")
        pool.buy(100, 1500)
        cost_basis = pool.sell(100, settled_amount=2000)
        assert cost_basis == 1500
        assert pool.quantity == 0
        assert pool.avg_cost == 0

    def test_spy_scenario(self):
        """SPY.US: buy 60 in 2024, sell 30 in 2024, sell 30 in 2025."""
        pool = CostPool("SPY.US")
        pool.buy(30, 30000)
        pool.buy(30, 31500)
        assert pool.avg_cost == pytest.approx(1025)

        cost_basis_2024 = pool.sell(30, settled_amount=32000)
        assert cost_basis_2024 == pytest.approx(30750)
        assert pool.avg_cost == pytest.approx(1025)

        cost_basis_2025 = pool.sell(30, settled_amount=33000)
        assert cost_basis_2025 == pytest.approx(30750)
        assert pool.quantity == 0


class TestShortPosition:
    """Sell-to-open then buy-to-close (short) operations."""

    def test_sell_to_open(self):
        pool = CostPool("OPT.US")
        cost_basis = pool.sell(2, settled_amount=5000)
        assert cost_basis == 0  # no realized gain on open
        assert pool.quantity == -2
        assert pool.is_short
        assert pool.avg_cost == 2500  # proceeds per unit

    def test_sell_to_open_then_buy_to_close(self):
        """NVDA put: sell @ 17.45, buy @ 5.25 (per share, ×100 already settled)."""
        pool = CostPool("NVDA251219P100000.US")

        # Sell to open: 2 contracts, proceeds = 2 * 17.45 * 100 * 7.3 = 25,477 CNY
        cost_basis = pool.sell(2, settled_amount=25477)
        assert cost_basis == 0
        assert pool.is_short

        # Buy to close: 2 contracts, cost = 2 * 5.25 * 100 * 7.3 = 7,665 CNY
        locked_proceeds = pool.buy(2, 7665)
        assert locked_proceeds == pytest.approx(25477)  # proceeds received at open
        assert pool.quantity == 0

    def test_expired_worthless_short(self):
        """SPY put sold, expires worthless — no buy-to-close, full profit."""
        pool = CostPool("SPY250402P535000.US")
        pool.sell(2, settled_amount=43.8)  # 2 * 0.03 * 100 * 7.3
        assert pool.quantity == -2
        assert pool.total_cost == pytest.approx(43.8)
        # Position stays open — profit realized when/if closed or at expiry

    def test_sell_to_open_requires_amount(self):
        pool = CostPool("TEST")
        with pytest.raises(ValueError, match="settled_amount"):
            pool.sell(2, settled_amount=0)


class TestEdgeCases:
    def test_sell_more_than_long_raises(self):
        pool = CostPool("TEST")
        pool.buy(10, 100)
        with pytest.raises(ValueError, match="cannot sell"):
            pool.sell(20, settled_amount=200)

    def test_buy_zero_raises(self):
        pool = CostPool("TEST")
        with pytest.raises(ValueError, match="positive"):
            pool.buy(0, 100)

    def test_sell_zero_raises(self):
        pool = CostPool("TEST")
        with pytest.raises(ValueError, match="positive"):
            pool.sell(0, settled_amount=100)

    def test_negative_cost_raises(self):
        pool = CostPool("TEST")
        with pytest.raises(ValueError, match="negative"):
            pool.buy(10, -100)

    def test_history_tracking(self):
        pool = CostPool("TEST")
        pool.buy(100, 1000)
        pool.sell(50, settled_amount=600)
        assert len(pool.history) == 2
        assert pool.history[0].side == 'BUY'
        assert pool.history[1].side == 'SELL'

    def test_float_dust_cleanup(self):
        pool = CostPool("TEST")
        pool.buy(3, 10)
        pool.sell(3, settled_amount=12)
        assert pool.quantity == 0
        assert pool.total_cost == 0
