"""Settlement calculator — converts raw trades to reporting currency amounts.

Encapsulates exchange rate conversion and fee handling.
Single responsibility: translate a trade into CNY net amounts.
"""

from datetime import datetime
from typing import Dict
from .exchange_rate import ExchangeRateManager


class SettlementCalculator:
    """Settles raw trades into reporting currency (CNY) net amounts."""

    def __init__(self, exchange: ExchangeRateManager):
        self.exchange = exchange

    def settle_buy(self, order: Dict) -> float:
        """Calculate total buy cost in CNY.

        Formula: (quantity * price + fees) * exchange_rate

        Returns:
            Total cost in CNY including fees.
        """
        rate = self._get_rate(order)
        gross = order['quantity'] * order['price']
        fees = self._extract_fees(order)
        return (gross + fees) * rate

    def settle_sell_with_rate(self, order: Dict) -> tuple[float, float]:
        """Calculate total sell proceeds in CNY and return the rate used.

        Formula: (quantity * price - fees) * exchange_rate

        Returns:
            (proceeds_cny, exchange_rate)
        """
        rate = self._get_rate(order)
        gross = order['quantity'] * order['price']
        fees = self._extract_fees(order)
        return (gross - fees) * rate, rate

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
