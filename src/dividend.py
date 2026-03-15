"""Dividend income tax calculation module.

Tax rules for Chinese tax residents:
  - Dividend income taxed at flat 20% (separate from comprehensive income).
  - Foreign withholding tax can be credited against China tax liability,
    but credit cannot exceed the China tax amount.

Data flow:
  cashflows table (raw API cache)
    → cashflow_parser.parse_dividends() (match withholding, H-share gross reconstruction)
    → DividendCalculator (CNY conversion, tax credit calculation)
"""

from datetime import datetime
from typing import Dict, List

from .database import DatabaseManager
from .exchange_rate import ExchangeRateManager
from .cashflow_parser import parse_dividends

# Cash flow types that are dividend-related.
_DIVIDEND_FLOW_NAMES = ['Cash Dividend', 'CO Other FEE']

CHINA_DIVIDEND_TAX_RATE = 0.20


class DividendCalculator:
    """Calculates dividend income tax with foreign tax credit."""

    def __init__(self, db: DatabaseManager, exchange: ExchangeRateManager):
        self.db = db
        self.exchange = exchange

    def calculate(self, year: int) -> Dict:
        """Calculate dividend tax for a year.

        Reads raw cash flows from DB, parses into dividends, then
        computes tax with foreign tax credit.
        """
        raw_entries = self.db.get_cashflows(year, _DIVIDEND_FLOW_NAMES)
        dividends, _ = parse_dividends(raw_entries)

        details = []
        total_gross_cny = 0.0
        total_withheld_cny = 0.0

        for div in dividends:
            detail = self._process(div)
            details.append(detail)
            total_gross_cny += detail['gross_cny']
            total_withheld_cny += detail['withheld_cny']

        total_china_tax = total_gross_cny * CHINA_DIVIDEND_TAX_RATE
        total_credit = min(total_withheld_cny, total_china_tax)
        total_tax_owed = max(0, total_china_tax - total_credit)

        return {
            'year': year,
            'details': details,
            'total_gross_cny': total_gross_cny,
            'total_withheld_cny': total_withheld_cny,
            'total_china_tax': total_china_tax,
            'total_credit': total_credit,
            'total_tax_owed': total_tax_owed,
        }

    def _process(self, div: Dict) -> Dict:
        """Convert one parsed dividend record to a tax detail line."""
        date = datetime.fromisoformat(div['received_at']).strftime('%Y-%m-%d')
        symbol = div['symbol']
        currency = div['currency']
        gross = div['amount']              # already normalized to gross by parser
        withheld = div.get('withholding', 0.0)
        net_amount = gross - withheld

        rate = self.exchange.get_rate(date, currency, 'CNY')

        return {
            'symbol': symbol,
            'date': date,
            'currency': currency,
            'net_amount': net_amount,
            'gross_amount': gross,
            'withheld': withheld,
            'exchange_rate': rate,
            'gross_cny': gross * rate,
            'withheld_cny': withheld * rate,
        }
