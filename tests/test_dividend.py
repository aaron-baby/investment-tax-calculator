"""Unit tests for DividendCalculator — withholding from DB, tax credit, CNY conversion."""

import pytest
from src.database import DatabaseManager
from src.exchange_rate import ExchangeRateManager, RateSource
from src.dividend import DividendCalculator, CHINA_DIVIDEND_TAX_RATE


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(tmp_path / 'test.db')


@pytest.fixture
def calc(db):
    exchange = ExchangeRateManager(db, provider=None)
    return DividendCalculator(db, exchange)


def _seed_rate(db, date, ccy, rate):
    db.save_exchange_rate(date, ccy, 'CNY', rate, RateSource.FRANKFURTER)


# --- DB round-trip ---

class TestDividendStorage:
    def test_save_and_retrieve(self, db):
        db.save_dividends([{
            'symbol': 'AAPL.US', 'currency': 'USD', 'amount': 44.0,
            'withholding': 4.4,
            'received_at': '2025-01-16T00:00:00', 'flow_name': 'Cash Dividend',
        }])
        result = db.get_dividends(2025)
        assert len(result) == 1
        assert result[0]['amount'] == 44.0
        assert result[0]['withholding'] == 4.4

    def test_duplicate_ignored(self, db):
        div = {
            'symbol': 'AAPL.US', 'currency': 'USD', 'amount': 44.0,
            'withholding': 4.4,
            'received_at': '2025-01-16T00:00:00', 'flow_name': 'Cash Dividend',
        }
        db.save_dividends([div])
        db.save_dividends([div])
        assert len(db.get_dividends(2025)) == 1

    def test_filter_by_year(self, db):
        db.save_dividends([
            {'symbol': 'A.US', 'currency': 'USD', 'amount': 10, 'withholding': 1,
             'received_at': '2024-06-01T00:00:00', 'flow_name': 'Cash Dividend'},
            {'symbol': 'B.US', 'currency': 'USD', 'amount': 20, 'withholding': 2,
             'received_at': '2025-06-01T00:00:00', 'flow_name': 'Cash Dividend'},
        ])
        assert len(db.get_dividends(2024)) == 1
        assert len(db.get_dividends(2025)) == 1

    def test_withholding_defaults_to_zero(self, db):
        db.save_dividends([{
            'symbol': 'X.HK', 'currency': 'HKD', 'amount': 100,
            'received_at': '2025-03-01T00:00:00', 'flow_name': 'Cash Dividend',
        }])
        result = db.get_dividends(2025)
        assert result[0]['withholding'] == 0.0


# --- Tax calculation ---

class TestDividendCalculation:
    def test_us_dividend_with_withholding(self, db, calc):
        """US stock: amount=$44 is gross, withheld=$4.40, net=$39.60."""
        _seed_rate(db, '2025-01-16', 'USD', 7.2)
        db.save_dividends([{
            'symbol': 'OXY.US', 'currency': 'USD', 'amount': 44.0,
            'withholding': 4.4,
            'received_at': '2025-01-16T00:00:00', 'flow_name': 'Cash Dividend',
        }])
        result = calc.calculate(2025)
        d = result['details'][0]

        # amount IS gross; net = gross - withheld
        assert d['gross_amount'] == pytest.approx(44.0)
        assert d['withheld'] == pytest.approx(4.4)
        assert d['net_amount'] == pytest.approx(39.6)
        assert d['gross_cny'] == pytest.approx(44.0 * 7.2)
        assert d['withheld_cny'] == pytest.approx(4.4 * 7.2)

        # China tax = gross_cny * 20%, credit = withheld_cny, owed = diff
        china_tax = 44.0 * 7.2 * 0.20
        credit = 4.4 * 7.2
        assert result['total_china_tax'] == pytest.approx(china_tax)
        assert result['total_credit'] == pytest.approx(credit)
        assert result['total_tax_owed'] == pytest.approx(china_tax - credit)

    def test_no_withholding(self, db, calc):
        """Dividend with zero withholding — full 20% owed."""
        _seed_rate(db, '2025-06-01', 'HKD', 0.92)
        db.save_dividends([{
            'symbol': '700.HK', 'currency': 'HKD', 'amount': 1000.0,
            'withholding': 0.0,
            'received_at': '2025-06-01T00:00:00', 'flow_name': 'Cash Dividend',
        }])
        result = calc.calculate(2025)
        assert result['total_credit'] == 0.0
        assert result['total_tax_owed'] == pytest.approx(1000.0 * 0.92 * 0.20)

    def test_no_dividends(self, calc):
        result = calc.calculate(2025)
        assert result['details'] == []
        assert result['total_tax_owed'] == 0.0

    def test_multiple_dividends_aggregated(self, db, calc):
        _seed_rate(db, '2025-01-16', 'USD', 7.2)
        _seed_rate(db, '2025-01-02', 'USD', 7.3)
        db.save_dividends([
            {'symbol': 'OXY.US', 'currency': 'USD', 'amount': 44.0,
             'withholding': 4.4,
             'received_at': '2025-01-16T00:00:00', 'flow_name': 'Cash Dividend'},
            {'symbol': 'SOXL.US', 'currency': 'USD', 'amount': 14.67,
             'withholding': 1.47,
             'received_at': '2025-01-02T00:00:00', 'flow_name': 'Cash Dividend'},
        ])
        result = calc.calculate(2025)
        assert len(result['details']) == 2
        assert result['total_gross_cny'] > 0
        assert result['total_tax_owed'] > 0

    def test_credit_capped_at_china_tax(self, db, calc):
        """If withholding exceeds 20% of gross, credit is capped."""
        _seed_rate(db, '2025-01-01', 'USD', 7.2)
        # amount=10 IS gross, withholding=5 (50% rate, way above 20%)
        # china_tax = 10 * 7.2 * 0.2 = 14.4
        # withheld_cny = 5 * 7.2 = 36 > 14.4 → credit capped at 14.4
        db.save_dividends([{
            'symbol': 'X.US', 'currency': 'USD', 'amount': 10.0,
            'withholding': 5.0,
            'received_at': '2025-01-01T00:00:00', 'flow_name': 'Cash Dividend',
        }])
        result = calc.calculate(2025)
        assert result['total_credit'] <= result['total_china_tax']
        assert result['total_tax_owed'] == 0.0  # fully covered by credit
