"""Unit tests for SettlementCalculator."""

import pytest
from unittest.mock import MagicMock
from src.settlement import SettlementCalculator


@pytest.fixture
def settlement():
    mock_exchange = MagicMock()
    mock_exchange.get_rate.return_value = 7.3  # USD->CNY
    return SettlementCalculator(mock_exchange)


class TestSettleBuy:
    def test_basic_buy_no_fees(self, settlement):
        order = {
            'quantity': 30, 'price': 580.0, 'currency': 'USD',
            'executed_at': '2024-12-01T10:00:00', 'fees': {},
        }
        result = settlement.settle_buy(order)
        # (30 * 580 + 0) * 7.3 = 127020
        assert result == pytest.approx(127020)

    def test_buy_with_fees(self, settlement):
        order = {
            'quantity': 30, 'price': 580.0, 'currency': 'USD',
            'executed_at': '2024-12-01T10:00:00',
            'fees': {'total_amount': '5.0'},
        }
        result = settlement.settle_buy(order)
        # (30 * 580 + 5) * 7.3 = 127056.5
        assert result == pytest.approx(127056.5)

    def test_buy_missing_fees(self, settlement):
        order = {
            'quantity': 10, 'price': 100.0, 'currency': 'USD',
            'executed_at': '2024-01-01T10:00:00',
        }
        result = settlement.settle_buy(order)
        assert result == pytest.approx(7300)


class TestSettleSellWithRate:
    def test_basic_sell_no_fees(self, settlement):
        order = {
            'quantity': 30, 'price': 600.0, 'currency': 'USD',
            'executed_at': '2024-12-19T10:00:00', 'fees': {},
        }
        proceeds, rate = settlement.settle_sell_with_rate(order)
        assert proceeds == pytest.approx(131400)
        assert rate == pytest.approx(7.3)

    def test_sell_with_fees(self, settlement):
        order = {
            'quantity': 30, 'price': 600.0, 'currency': 'USD',
            'executed_at': '2024-12-19T10:00:00',
            'fees': {'total_amount': '10.0'},
        }
        proceeds, rate = settlement.settle_sell_with_rate(order)
        # (30 * 600 - 10) * 7.3 = 131327
        assert proceeds == pytest.approx(131327)
        assert rate == pytest.approx(7.3)


class TestFeeExtraction:
    def test_empty_fees(self, settlement):
        assert settlement._extract_fees({}) == 0
        assert settlement._extract_fees({'fees': {}}) == 0
        assert settlement._extract_fees({'fees': None}) == 0

    def test_string_amount(self, settlement):
        assert settlement._extract_fees({'fees': {'total_amount': '12.50'}}) == 12.50

    def test_numeric_amount(self, settlement):
        assert settlement._extract_fees({'fees': {'total_amount': 8.0}}) == 8.0

    def test_invalid_amount(self, settlement):
        assert settlement._extract_fees({'fees': {'total_amount': 'N/A'}}) == 0
