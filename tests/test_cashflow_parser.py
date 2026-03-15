"""Tests for cashflow_parser — symbol extraction, withholding matching."""

import pytest
from src.cashflow_parser import (
    parse_dividends,
    summarize_by_symbol,
    _extract_symbol,
    _is_withholding,
    _parse_embedded_wht,
)


def _entry(name, balance, currency='USD', symbol=None, desc='',
           business_time='2025-01-16T00:00:00', direction='IN'):
    """Build a raw cash flow entry matching the API/DB schema."""
    return {
        'transaction_flow_name': name,
        'direction': direction,
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


class TestParseEmbeddedWht:
    def test_hk_h_share_10pct(self):
        desc = '#1919.HK COSCO SHIP HOLD: 25 I/D-RMB0.56/SH(-10%), PAY IN APPROX. HKD0.5525495999/SH(NET)'
        assert _parse_embedded_wht(desc) == pytest.approx(0.10)

    def test_hk_h_share_20pct(self):
        assert _parse_embedded_wht('HKD1.00/SH(-20%), PAY IN HKD0.80(NET)') == pytest.approx(0.20)

    def test_no_embedded_rate(self):
        assert _parse_embedded_wht('OXY.US Cash Dividend: 0.22 USD per Share') is None

    def test_non_h_share_hk(self):
        assert _parse_embedded_wht('#9988.HK BABA-W: 24/25 F/D-USD0.13125/SH') is None


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

    def test_h_share_back_calculates_gross(self):
        """H-share with (-10%): balance is NET, parser should reconstruct gross."""
        entries = [
            _entry('Cash Dividend', 2970.0, currency='HKD',
                   desc='#883.HK CNOOC: 24 F/D-HKD0.66/SH(-10%), PAY IN HKD0.594(NET)'),
        ]
        divs, _ = parse_dividends(entries)
        assert len(divs) == 1
        assert divs[0]['amount'] == pytest.approx(3300.0)       # gross
        assert divs[0]['withholding'] == pytest.approx(330.0)   # 10% of gross


class TestSummarizeBySymbol:
    def test_aggregation(self):
        divs = [
            {'symbol': 'A.US', 'amount': 10.0, 'withholding': 1.0},
            {'symbol': 'B.US', 'amount': 20.0, 'withholding': 2.0},
            {'symbol': 'A.US', 'amount': 5.0, 'withholding': 0.5},
        ]
        result = summarize_by_symbol(divs)
        assert result == {'A.US': 13.5, 'B.US': 18.0}
