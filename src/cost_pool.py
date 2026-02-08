"""Weighted average cost pool for tracking position cost basis.

Pure computation module with zero external dependencies.
Accepts pre-settled amounts in reporting currency (CNY).

Supports both long (buy-first) and short (sell-first) positions.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class PoolTransaction:
    """Record of a cost pool state change."""
    side: str           # BUY or SELL
    quantity: float
    amount: float       # settled amount in reporting currency
    avg_cost_after: float
    quantity_after: float
    total_cost_after: float


class CostPool:
    """Weighted average cost pool for a single symbol.

    Long position (buy then sell):
      - buy() adds to pool
      - sell() removes at avg cost, returns cost_basis

    Short position (sell-to-open then buy-to-close):
      - sell() on empty pool opens short, records proceeds as "cost"
      - buy() on short pool closes at avg proceeds, returns cost_basis (the proceeds locked in)

    In both cases the caller computes gain/loss = proceeds - cost_basis.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._quantity: float = 0       # positive = long, negative = short
        self._total_cost: float = 0     # for long: total cost; for short: total proceeds received
        self._history: List[PoolTransaction] = []

    @property
    def quantity(self) -> float:
        return self._quantity

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def avg_cost(self) -> float:
        """Per-unit weighted average cost (or proceeds for short)."""
        if abs(self._quantity) < 1e-9:
            return 0
        return self._total_cost / abs(self._quantity)

    @property
    def history(self) -> List[PoolTransaction]:
        return list(self._history)

    @property
    def is_short(self) -> bool:
        return self._quantity < -1e-9

    @property
    def is_long(self) -> bool:
        return self._quantity > 1e-9

    def buy(self, qty: float, settled_amount: float) -> float:
        """Process a buy.

        If long or flat: adds to long position, returns 0 (no realized gain).
        If short: closes short position, returns the locked-in proceeds (cost_basis).

        Args:
            qty: number of units
            settled_amount: total amount in reporting currency

        Returns:
            cost_basis for closing a short position, or 0 for opening/adding long.
        """
        if qty <= 0:
            raise ValueError(f"Buy quantity must be positive, got {qty}")
        if settled_amount < 0:
            raise ValueError(f"Settled amount cannot be negative, got {settled_amount}")

        if self.is_short:
            # Closing short: return the avg proceeds locked in at open
            close_qty = min(qty, abs(self._quantity))
            cost_basis = close_qty * self.avg_cost  # proceeds received when opening short
            self._quantity += close_qty
            self._total_cost -= cost_basis
            self._cleanup()
            self._record('BUY', close_qty, cost_basis)

            # If buying more than short position, remainder opens long
            remainder = qty - close_qty
            if remainder > 1e-9:
                # Proportional cost for the remainder
                remainder_cost = settled_amount * (remainder / qty)
                self._quantity += remainder
                self._total_cost += remainder_cost
                self._record('BUY', remainder, remainder_cost)

            return cost_basis
        else:
            # Opening/adding long
            self._quantity += qty
            self._total_cost += settled_amount
            self._record('BUY', qty, settled_amount)
            return 0

    def sell(self, qty: float, settled_amount: float = 0) -> float:
        """Process a sell.

        If long: closes long position, returns cost_basis (avg cost of shares sold).
        If flat or short: opens/adds to short position, returns 0.

        Args:
            qty: number of units
            settled_amount: total proceeds in reporting currency (needed for short opens)

        Returns:
            cost_basis for closing a long position, or 0 for opening short.
        """
        if qty <= 0:
            raise ValueError(f"Sell quantity must be positive, got {qty}")

        if self.is_long:
            # Closing long
            if qty > self._quantity + 1e-9:
                raise ValueError(
                    f"{self.symbol}: cannot sell {qty}, only holding {self._quantity}"
                )
            cost_basis = qty * self.avg_cost
            self._quantity -= qty
            self._total_cost -= cost_basis
            self._cleanup()
            self._record('SELL', qty, cost_basis)
            return cost_basis
        else:
            # Opening/adding short: record the proceeds received
            if settled_amount <= 0:
                raise ValueError(
                    f"{self.symbol}: sell-to-open requires settled_amount > 0"
                )
            self._quantity -= qty
            self._total_cost += settled_amount
            self._record('SELL', qty, settled_amount)
            return 0

    def _cleanup(self):
        """Clean up float dust when position is flat."""
        if abs(self._quantity) < 1e-9:
            self._quantity = 0
            self._total_cost = 0

    def _record(self, side: str, qty: float, amount: float):
        self._history.append(PoolTransaction(
            side=side,
            quantity=qty,
            amount=amount,
            avg_cost_after=self.avg_cost,
            quantity_after=self._quantity,
            total_cost_after=self._total_cost,
        ))
