"""Unit tests for DividendCalculator — reads raw cashflows, tax credit, CNY conversion."""

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


def _cashflow(name, balance, currency='USD', symbol=None, desc='',
              business_time='2025-01-16T00:00:00', direction='IN'):
    """Build a raw cash flow entry matching the API/DB schema."""
    return {
        'transaction_flow_name': name,
        'direction': direction,
        'balance': balance,
        'currency': currency,
        'business_time': business_time,
        'symbol': symbol,
        'description': desc,
    }


# --- DB round-trip (cashflows table) ---

class TestCashflowStorage:
    def test_save_and_retrieve(self, db):
        db.save_cashflows([
            _cashflow('Cash Dividend', 44.0, desc='OXY.US Cash Dividend'),
        ])
        result = db.get_cashflows(2025)
        assert len(result) == 1
        assert result[0]['balance'] == 44.0

    def test_duplicate_ignored(self, db):
        entry = _cashflow('Cash Dividend', 44.0, desc='OXY.US Cash Dividend')
        db.save_cashflows([entry])
        db.save_cashflows([entry])
        assert len(db.get_cashflows(2025)) == 1

    def test_filter_by_year(self, db):
        db.save_cashflows([
            _cashflow('Cash Dividend', 10, business_time='2024-06-01T00:00:00'),
            _cashflow('Cash Dividend', 20, business_time='2025-06-01T00:00:00'),
        ])
        assert len(db.get_cashflows(2024)) == 1
        assert len(db.get_cashflows(2025)) == 1

    def test_filter_by_flow_name(self, db):
        db.save_cashflows([
            _cashflow('Cash Dividend', 44.0),
            _cashflow('CO Other FEE', -4.4, business_time='2025-01-16T00:00:30'),
            _cashflow('Commission', 5.0, business_time='2025-01-16T01:00:00'),
        ])
        result = db.get_cashflows(2025, ['Cash Dividend', 'CO Other FEE'])
        assert len(result) == 2


# --- Tax calculation (end-to-end: cashflows → parser → calculator) ---

class TestDividendCalculation:
    def test_us_dividend_with_withholding(self, db, calc):
        """US stock: amount=$44 is gross, withheld=$4.40 from CO Other FEE."""
        _seed_rate(db, '2025-01-16', 'USD', 7.2)
        db.save_cashflows([
            _cashflow('Cash Dividend', 44.0,
                      desc='OXY.US Cash Dividend: 0.22 USD per Share',
                      business_time='2025-01-16T10:00:00'),
            _cashflow('CO Other FEE', -4.4,
                      desc='OXY.US Withholding Tax/Dividend Fee',
                      business_time='2025-01-16T10:00:30',
                      direction='OUT'),
        ])
        result = calc.calculate(2025)
        d = result['details'][0]

        assert d['gross_amount'] == pytest.approx(44.0)
        assert d['withheld'] == pytest.approx(4.4)
        assert d['net_amount'] == pytest.approx(39.6)
        assert d['gross_cny'] == pytest.approx(44.0 * 7.2)
        assert d['withheld_cny'] == pytest.approx(4.4 * 7.2)

        china_tax = 44.0 * 7.2 * 0.20
        credit = 4.4 * 7.2
        assert result['total_china_tax'] == pytest.approx(china_tax)
        assert result['total_credit'] == pytest.approx(credit)
        assert result['total_tax_owed'] == pytest.approx(china_tax - credit)

    def test_hk_h_share_embedded_withholding(self, db, calc):
        """HK H-share: balance is NET, description has (-10%), back-calculate gross."""
        _seed_rate(db, '2025-06-01', 'HKD', 0.92)
        # 883.HK CNOOC: balance=2970 is NET (after 10% deduction)
        # gross = 2970 / 0.9 = 3300, withholding = 330
        db.save_cashflows([
            _cashflow('Cash Dividend', 2970.0, currency='HKD',
                      desc='#883.HK CNOOC: 24 F/D-HKD0.66/SH(-10%), PAY IN HKD0.594(NET)',
                      business_time='2025-06-01T00:00:00'),
        ])
        result = calc.calculate(2025)
        d = result['details'][0]

        assert d['gross_amount'] == pytest.approx(3300.0)
        assert d['withheld'] == pytest.approx(330.0)
        assert d['net_amount'] == pytest.approx(2970.0)

    def test_hk_non_h_share_no_withholding(self, db, calc):
        """HK non-H-share (e.g. BABA-W): amount is gross, no withholding, full 20% tax."""
        _seed_rate(db, '2025-06-01', 'USD', 7.2)
        db.save_cashflows([
            _cashflow('Cash Dividend', 50.0, currency='USD',
                      desc='#9988.HK BABA-W: 24/25 F/D-USD0.13125/SH',
                      business_time='2025-06-01T00:00:00'),
        ])
        result = calc.calculate(2025)
        d = result['details'][0]

        assert d['gross_amount'] == pytest.approx(50.0)
        assert d['withheld'] == pytest.approx(0.0)
        assert result['total_credit'] == 0.0
        assert result['total_tax_owed'] == pytest.approx(50.0 * 7.2 * 0.20)

    def test_no_dividends(self, calc):
        result = calc.calculate(2025)
        assert result['details'] == []
        assert result['total_tax_owed'] == 0.0

    def test_multiple_dividends_aggregated(self, db, calc):
        _seed_rate(db, '2025-01-16', 'USD', 7.2)
        _seed_rate(db, '2025-01-02', 'USD', 7.3)
        db.save_cashflows([
            _cashflow('Cash Dividend', 44.0,
                      desc='OXY.US Cash Dividend',
                      business_time='2025-01-16T10:00:00'),
            _cashflow('CO Other FEE', -4.4,
                      desc='OXY.US Withholding Tax/Dividend Fee',
                      business_time='2025-01-16T10:00:30',
                      direction='OUT'),
            _cashflow('Cash Dividend', 14.67,
                      desc='SOXL.US Cash Dividend',
                      business_time='2025-01-02T10:00:00'),
            _cashflow('CO Other FEE', -1.47,
                      desc='SOXL.US Withholding Tax/Dividend Fee',
                      business_time='2025-01-02T10:00:30',
                      direction='OUT'),
        ])
        result = calc.calculate(2025)
        assert len(result['details']) == 2
        assert result['total_gross_cny'] > 0
        assert result['total_tax_owed'] > 0

    def test_credit_capped_at_china_tax(self, db, calc):
        """If withholding exceeds 20% of gross, credit is capped."""
        _seed_rate(db, '2025-01-01', 'USD', 7.2)
        # gross=10, withholding=5 (50% rate, way above 20%)
        # china_tax = 10 * 7.2 * 0.2 = 14.4
        # withheld_cny = 5 * 7.2 = 36 > 14.4 → credit capped at 14.4
        db.save_cashflows([
            _cashflow('Cash Dividend', 10.0,
                      desc='X.US Cash Dividend',
                      business_time='2025-01-01T10:00:00'),
            _cashflow('CO Other FEE', -5.0,
                      desc='X.US Withholding Tax/Dividend Fee',
                      business_time='2025-01-01T10:00:30',
                      direction='OUT'),
        ])
        result = calc.calculate(2025)
        assert result['total_credit'] <= result['total_china_tax']
        assert result['total_tax_owed'] == 0.0
