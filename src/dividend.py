"""Dividend income tax calculation module.

Tax rules for Chinese tax residents:
  - Dividend income taxed at flat 20% (separate from comprehensive income).
  - Foreign withholding tax can be credited against China tax liability,
    but credit cannot exceed the China tax amount.

Data source:
  The `dividends` DB table stores net dividend received (`amount`) and
  the actual foreign withholding tax (`withholding`), both in original
  currency.  These come from the Long Bridge Cash Flow API:
    - "Cash Dividend" entries → amount
    - "CO Other FEE" / Withholding Tax entries → withholding
  Gross = amount + withholding.
"""

from datetime import datetime
from typing import Dict, List

from .database import DatabaseManager
from .exchange_rate import ExchangeRateManager

CHINA_DIVIDEND_TAX_RATE = 0.20


class DividendCalculator:
    """Calculates dividend income tax with foreign tax credit."""

    def __init__(self, db: DatabaseManager, exchange: ExchangeRateManager):
        self.db = db
        self.exchange = exchange

    def calculate(self, year: int) -> Dict:
        """Calculate dividend tax for a year.

        Returns dict with details list and aggregated totals.
        """
        dividends = self.db.get_dividends(year)

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
        """Convert one dividend record to a tax detail line."""
        date = datetime.fromisoformat(div['received_at']).strftime('%Y-%m-%d')
        symbol = div['symbol']
        currency = div['currency']
        net_amount = div['amount']
        withheld = div.get('withholding', 0.0)
        gross = net_amount + withheld

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
