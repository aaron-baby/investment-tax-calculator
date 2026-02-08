"""Unit tests for SettlementCalculator and get_multiplier."""

import pytest
from unittest.mock import MagicMock
from src.settlement import SettlementCalculator, get_multiplier


# --- get_multiplier tests ---

class TestGetMultiplier:
    def test_us_stock(self):
        assert get_multiplier('AAPL.US') == 1
        assert get_multiplier('SPY.US') == 1
        assert get_multiplier('BRK.B.US') == 1

    def test_hk_stock(self):
        assert get_multiplier('1378.HK') == 1
        assert get_multiplier('9988.HK') == 1

    def test_us_call_option(self):
        assert get_multiplier('AMD250718C130000.US') == 100
        assert get_multiplier('AAPL260116C210000.US') == 100
        assert get_multiplier('RKLB260417C70000.US') == 100

    def test_us_put_option(self):
        assert get_multiplier('SPY250402P535000.US') == 100
        assert get_multiplier('NVDA251219P100000.US') == 100
        assert get_multiplier('AAPL260116P195000.US') == 100

    def test_leveraged_etf_not_option(self):
        assert get_multiplier('AMDL.US') == 1
        assert get_multiplier('SOXL.US') == 1


# --- SettlementCalculator tests ---

@pytest.fixture
def settlement():
    mock_exchange = MagicMock()
    mock_exchange.get_rate.return_value = 7.3  # USD->CNY
    return SettlementCalculator(mock_exchange)


class TestSettleBuyStock:
    def test_basic_buy_no_fees(self, settlement):
        order = {
            'quantity': 30, 'price': 580.0, 'currency': 'USD',
            'executed_at': '2024-12-01T10:00:00', 'fees': {},
            'symbol': 'SPY.US',
        }
        result = settlement.settle_buy(order)
        # (30 * 580 * 1 + 0) * 7.3 = 127020
        assert result == pytest.approx(127020)

    def test_buy_with_fees(self, settlement):
        order = {
            'quantity': 30, 'price': 580.0, 'currency': 'USD',
            'executed_at': '2024-12-01T10:00:00', 'symbol': 'SPY.US',
            'fees': {'total_amount': '5.0'},
        }
        result = settlement.settle_buy(order)
        assert result == pytest.approx((30 * 580 + 5) * 7.3)


class TestSettleBuyOption:
    def test_option_buy_applies_multiplier(self, settlement):
        order = {
            'quantity': 4, 'price': 5.38, 'currency': 'USD',
            'executed_at': '2025-02-05T10:00:00', 'fees': {},
            'symbol': 'AMD250718C130000.US',
        }
        result = settlement.settle_buy(order)
        # (4 * 5.38 * 100 + 0) * 7.3 = 2152 * 7.3 = 15709.6
        assert result == pytest.approx(4 * 5.38 * 100 * 7.3)

    def test_option_buy_with_fees(self, settlement):
        order = {
            'quantity': 4, 'price': 5.38, 'currency': 'USD',
            'executed_at': '2025-02-05T10:00:00',
            'symbol': 'AMD250718C130000.US',
            'fees': {'total_amount': '2.60'},
        }
        result = settlement.settle_buy(order)
        assert result == pytest.approx((4 * 5.38 * 100 + 2.60) * 7.3)


class TestSettleSellWithRate:
    def test_stock_sell(self, settlement):
        order = {
            'quantity': 30, 'price': 600.0, 'currency': 'USD',
            'executed_at': '2024-12-19T10:00:00', 'fees': {},
            'symbol': 'SPY.US',
        }
        proceeds, rate = settlement.settle_sell_with_rate(order)
        assert proceeds == pytest.approx(131400)
        assert rate == pytest.approx(7.3)

    def test_option_sell_applies_multiplier(self, settlement):
        order = {
            'quantity': 2, 'price': 6.4, 'currency': 'USD',
            'executed_at': '2025-02-06T10:00:00', 'fees': {},
            'symbol': 'AMD250718C130000.US',
        }
        proceeds, rate = settlement.settle_sell_with_rate(order)
        # (2 * 6.4 * 100 - 0) * 7.3 = 1280 * 7.3 = 9344
        assert proceeds == pytest.approx(2 * 6.4 * 100 * 7.3)
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
