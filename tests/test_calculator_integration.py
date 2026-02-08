"""Integration test: verifies the full calculation pipeline with real DB data.

Uses the existing SQLite database to validate that historical cost pools
are correctly built across years.
"""

import pytest
from pathlib import Path
from src.database import DatabaseManager
from src.exchange_rate import ExchangeRateManager
from src.settlement import SettlementCalculator
from src.calculator import TaxCalculator

DB_PATH = Path('data/tax_calculator.db')


@pytest.fixture
def calculator():
    if not DB_PATH.exists():
        pytest.skip("No database found — run import-data first")
    db = DatabaseManager(DB_PATH)
    exchange = ExchangeRateManager(db)
    settlement = SettlementCalculator(exchange)
    return TaxCalculator(db, settlement, tax_rate=0.20)


class TestWithRealData:
    def test_2024_has_results(self, calculator):
        """Smoke test: 2024 calculation should produce results."""
        results = calculator.calculate(2024)
        assert len(results['details']) > 0
        assert results['total_gains'] >= 0

    def test_1378hk_cost_basis_positive(self, calculator):
        """1378.HK: cost basis should be positive (not zero)."""
        results = calculator.calculate(2024)
        hk_txs = [d for d in results['details'] if d['symbol'] == '1378.HK']
        for tx in hk_txs:
            assert tx['cost_basis_cny'] > 0, "Cost basis should not be zero"

    def test_spy_cost_basis_uses_history(self, calculator):
        """SPY.US: if 2024 has both buys and sells, cost basis should reflect buys."""
        results = calculator.calculate(2024)
        spy_txs = [d for d in results['details'] if d['symbol'] == 'SPY.US']
        for tx in spy_txs:
            assert tx['cost_basis_cny'] > 0, "SPY cost basis should use historical buys"
            # Proceeds and cost should be in reasonable range (not zero, not absurd)
            assert tx['proceeds_cny'] > 1000
            assert tx['cost_basis_cny'] > 1000
