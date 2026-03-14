"""Tests for cashflow_parser — symbol extraction, withholding matching."""

import pytest
from src.cashflow_parser import (
    parse_dividends,
    summarize_by_symbol,
    _extract_symbol,
    _is_withholding,
)


def _entry(name, balance, currency='USD', symbol=None, desc='',
           business_time='2025-01-16T00:00:00'):
    return {
        'transaction_flow_name': name,
        'balance': balance,
        'currency': currency,
        'symbol': symbol,
        'description': desc,
        'business_time': business_time,
    }


class TestExtractSymbol:
    def test_from_symbol_field(self):
        assert _extract_symbol('AAPL.US', '') == 'AAPL.US'

    def test_hk_symbol_strips_hash(self):
        assert _extract_symbol('#00700', '') == '00700.US'

    def test_from_description(self):
        assert _extract_symbol(None, 'OXY.US Cash Dividend: 0.22 USD') == 'OXY.US'

    def test_no_market_suffix_defaults_us(self):
        assert _extract_symbol(None, 'AAPL Cash Dividend') == 'AAPL.US'

    def test_none_when_unparseable(self):
        assert _extract_symbol(None, '') is None


class TestIsWithholding:
    def test_withholding_tax(self):
        assert _is_withholding('OXY.US Withholding Tax/Dividend Fee')

    def test_dividend_fee(self):
        assert _is_withholding('Some Dividend Fee entry')

    def test_not_withholding(self):
        assert not _is_withholding('Cash Dividend: 0.22 USD per Share')


class TestParseDividends:
    def test_basic_dividend_no_withholding(self):
        entries = [_entry('Cash Dividend', 44.0, desc='OXY.US Cash Dividend')]
        divs, unmatched = parse_dividends(entries)
        assert len(divs) == 1
        assert divs[0]['symbol'] == 'OXY.US'
        assert divs[0]['withholding'] == 0.0
        assert unmatched == []

    def test_matched_withholding(self):
        entries = [
            _entry('Cash Dividend', 44.0, desc='OXY.US Cash Dividend',
                   business_time='2025-01-16T10:00:00'),
            _entry('CO Other FEE', -4.4, desc='OXY.US Withholding Tax/Dividend Fee',
                   business_time='2025-01-16T10:00:30'),
        ]
        divs, unmatched = parse_dividends(entries)
        assert len(divs) == 1
        assert divs[0]['withholding'] == pytest.approx(4.4)
        assert unmatched == []

    def test_unmatched_withholding_outside_window(self):
        entries = [
            _entry('Cash Dividend', 44.0, desc='OXY.US Cash Dividend',
                   business_time='2025-01-16T10:00:00'),
            _entry('CO Other FEE', -4.4, desc='OXY.US Withholding Tax/Dividend Fee',
                   business_time='2025-01-16T10:05:00'),  # 5 min > 120s window
        ]
        divs, unmatched = parse_dividends(entries)
        assert divs[0]['withholding'] == 0.0
        assert len(unmatched) == 1

    def test_negative_balance_dividend_skipped(self):
        entries = [_entry('Cash Dividend', -10.0, desc='OXY.US Cash Dividend')]
        divs, _ = parse_dividends(entries)
        assert len(divs) == 0

    def test_non_dividend_entries_ignored(self):
        entries = [_entry('Commission', 5.0, desc='Commission fee')]
        divs, _ = parse_dividends(entries)
        assert len(divs) == 0


class TestSummarizeBySymbol:
    def test_aggregation(self):
        divs = [
            {'symbol': 'A.US', 'amount': 10.0},
            {'symbol': 'B.US', 'amount': 20.0},
            {'symbol': 'A.US', 'amount': 5.0},
        ]
        result = summarize_by_symbol(divs)
        assert result == {'A.US': 15.0, 'B.US': 20.0}
