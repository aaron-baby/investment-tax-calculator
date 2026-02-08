"""Settlement calculator — converts raw trades to reporting currency amounts.

Encapsulates exchange rate conversion, fee handling, and contract multipliers.
Single responsibility: translate a trade into CNY net amounts.
"""

import re
from datetime import datetime
from typing import Dict
from .exchange_rate import ExchangeRateManager

# US equity options: TICKER + YYMMDD + C/P + strike price + .US
_OPTION_PATTERN = re.compile(r'^.+\d{6}[CP]\d+\.US$')


def get_multiplier(symbol: str) -> int:
    """Return the contract multiplier for a symbol.

    US equity options: 1 contract = 100 shares → multiplier = 100
    Everything else (stocks, ETFs, HK stocks): multiplier = 1
    """
    if _OPTION_PATTERN.match(symbol):
        return 100
    return 1


class SettlementCalculator:
    """Settles raw trades into reporting currency (CNY) net amounts."""

    def __init__(self, exchange: ExchangeRateManager):
        self.exchange = exchange

    def settle_buy(self, order: Dict) -> float:
        """Calculate total buy cost in CNY.

        Formula: (quantity * price * multiplier + fees) * exchange_rate
        """
        rate = self._get_rate(order)
        gross = self._gross(order)
        fees = self._extract_fees(order)
        return (gross + fees) * rate

    def settle_sell_with_rate(self, order: Dict) -> tuple[float, float]:
        """Calculate total sell proceeds in CNY and return the rate used.

        Formula: (quantity * price * multiplier - fees) * exchange_rate

        Returns:
            (proceeds_cny, exchange_rate)
        """
        rate = self._get_rate(order)
        gross = self._gross(order)
        fees = self._extract_fees(order)
        return (gross - fees) * rate, rate

    def get_rate_for_order(self, order: Dict) -> float:
        """Get the exchange rate for an order (public, for reporting)."""
        return self._get_rate(order)

    @staticmethod
    def _gross(order: Dict) -> float:
        """Calculate gross trade value in original currency."""
        return order['quantity'] * order['price'] * get_multiplier(order['symbol'])

    def _get_rate(self, order: Dict) -> float:
        """Get exchange rate for the order's execution date."""
        date = self._parse_date(order['executed_at'])
        return self.exchange.get_rate(date, order['currency'], 'CNY')

    @staticmethod
    def _extract_fees(order: Dict) -> float:
        """Extract total fees from order in original currency."""
        fees = order.get('fees', {})
        if not fees:
            return 0
        total = fees.get('total_amount', 0)
        try:
            return float(total)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_date(executed_at: str) -> str:
        """Extract YYYY-MM-DD from ISO datetime string."""
        return datetime.fromisoformat(executed_at).strftime('%Y-%m-%d')
