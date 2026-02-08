"""Unit tests for CostPool — the core cost tracking module."""

import pytest
from src.cost_pool import CostPool


class TestCostPoolBasic:
    """Basic buy/sell operations."""

    def test_single_buy(self):
        pool = CostPool("TEST")
        pool.buy(100, 1000)  # 100 shares, 1000 CNY total
        assert pool.quantity == 100
        assert pool.total_cost == 1000
        assert pool.avg_cost == 10

    def test_two_buys_weighted_average(self):
        pool = CostPool("TEST")
        pool.buy(100, 1000)   # 100 @ 10
        pool.buy(100, 2000)   # 100 @ 20
        assert pool.quantity == 200
        assert pool.total_cost == 3000
        assert pool.avg_cost == 15

    def test_buy_then_sell(self):
        pool = CostPool("TEST")
        pool.buy(100, 1000)
        cost_basis = pool.sell(50)
        assert cost_basis == 500  # 50 * 10
        assert pool.quantity == 50
        assert pool.total_cost == 500
        assert pool.avg_cost == 10  # avg unchanged after sell

    def test_sell_all(self):
        pool = CostPool("TEST")
        pool.buy(100, 1500)
        cost_basis = pool.sell(100)
        assert cost_basis == 1500
        assert pool.quantity == 0
        assert pool.total_cost == 0
        assert pool.avg_cost == 0


class TestCostPoolMultipleTransactions:
    """Simulates realistic trading scenarios."""

    def test_spy_scenario(self):
        """SPY.US: buy 60 in 2024, sell 30 in 2024, sell 30 in 2025.
        
        Verifies that the 2025 sell uses the correct historical avg cost.
        """
        pool = CostPool("SPY.US")

        # 2024: buy 30 @ cost 30000 CNY, buy 30 @ cost 31500 CNY
        pool.buy(30, 30000)
        pool.buy(30, 31500)
        assert pool.quantity == 60
        assert pool.avg_cost == pytest.approx(1025)  # 61500/60

        # 2024: sell 30
        cost_basis_2024 = pool.sell(30)
        assert cost_basis_2024 == pytest.approx(30750)  # 30 * 1025
        assert pool.quantity == 30
        assert pool.avg_cost == pytest.approx(1025)  # avg unchanged

        # 2025: sell remaining 30
        cost_basis_2025 = pool.sell(30)
        assert cost_basis_2025 == pytest.approx(30750)  # 30 * 1025
        assert pool.quantity == 0

    def test_multiple_buys_partial_sells(self):
        """Buy at different prices, sell in chunks."""
        pool = CostPool("1378.HK")

        pool.buy(500, 4400)   # 500 @ 8.8 CNY/share
        pool.buy(300, 3000)   # 300 @ 10 CNY/share
        # avg = 7400/800 = 9.25

        assert pool.avg_cost == pytest.approx(9.25)

        # Sell 200
        cb1 = pool.sell(200)
        assert cb1 == pytest.approx(1850)  # 200 * 9.25
        assert pool.quantity == 600
        assert pool.avg_cost == pytest.approx(9.25)  # unchanged

        # Buy more at higher price
        pool.buy(400, 5000)  # 400 @ 12.5 CNY/share
        # new total: 600*9.25 + 5000 = 5550 + 5000 = 10550, qty = 1000
        assert pool.avg_cost == pytest.approx(10.55)

        # Sell 500
        cb2 = pool.sell(500)
        assert cb2 == pytest.approx(5275)  # 500 * 10.55


class TestCostPoolEdgeCases:
    """Edge cases and error handling."""

    def test_sell_more_than_holding_raises(self):
        pool = CostPool("TEST")
        pool.buy(10, 100)
        with pytest.raises(ValueError, match="cannot sell"):
            pool.sell(20)

    def test_buy_zero_raises(self):
        pool = CostPool("TEST")
        with pytest.raises(ValueError, match="positive"):
            pool.buy(0, 100)

    def test_sell_zero_raises(self):
        pool = CostPool("TEST")
        pool.buy(10, 100)
        with pytest.raises(ValueError, match="positive"):
            pool.sell(0)

    def test_negative_cost_raises(self):
        pool = CostPool("TEST")
        with pytest.raises(ValueError, match="negative"):
            pool.buy(10, -100)

    def test_history_tracking(self):
        pool = CostPool("TEST")
        pool.buy(100, 1000)
        pool.sell(50)
        assert len(pool.history) == 2
        assert pool.history[0].side == 'BUY'
        assert pool.history[1].side == 'SELL'

    def test_float_dust_cleanup(self):
        """Selling all shares should result in exactly 0, not float dust."""
        pool = CostPool("TEST")
        pool.buy(3, 10)
        pool.sell(3)
        assert pool.quantity == 0
        assert pool.total_cost == 0
