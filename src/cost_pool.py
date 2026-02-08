"""Weighted average cost pool for tracking position cost basis.

Pure computation module with zero external dependencies.
Accepts pre-settled amounts in reporting currency (CNY).
"""

from dataclasses import dataclass, field
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

    Tracks quantity and total cost in reporting currency.
    On buy: adds to pool.
    On sell: removes at current weighted average cost.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._quantity: float = 0
        self._total_cost: float = 0
        self._history: List[PoolTransaction] = []

    @property
    def quantity(self) -> float:
        return self._quantity

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def avg_cost(self) -> float:
        """Per-share weighted average cost in reporting currency."""
        if self._quantity <= 0:
            return 0
        return self._total_cost / self._quantity

    @property
    def history(self) -> List[PoolTransaction]:
        return list(self._history)

    def buy(self, qty: float, settled_cost: float) -> None:
        """Add shares to the pool.

        Args:
            qty: number of shares bought
            settled_cost: total cost in reporting currency (price * qty + fees) * rate
        """
        if qty <= 0:
            raise ValueError(f"Buy quantity must be positive, got {qty}")
        if settled_cost < 0:
            raise ValueError(f"Settled cost cannot be negative, got {settled_cost}")

        self._quantity += qty
        self._total_cost += settled_cost

        self._history.append(PoolTransaction(
            side='BUY',
            quantity=qty,
            amount=settled_cost,
            avg_cost_after=self.avg_cost,
            quantity_after=self._quantity,
            total_cost_after=self._total_cost,
        ))

    def sell(self, qty: float) -> float:
        """Remove shares from the pool at weighted average cost.

        Args:
            qty: number of shares to sell

        Returns:
            cost_basis: the cost basis for this sale in reporting currency

        Raises:
            ValueError: if selling more than current holdings
        """
        if qty <= 0:
            raise ValueError(f"Sell quantity must be positive, got {qty}")
        if qty > self._quantity + 1e-9:  # small tolerance for float
            raise ValueError(
                f"{self.symbol}: cannot sell {qty}, only holding {self._quantity}"
            )

        cost_basis = qty * self.avg_cost
        self._quantity -= qty
        self._total_cost -= cost_basis

        # Clean up float dust
        if abs(self._quantity) < 1e-9:
            self._quantity = 0
            self._total_cost = 0

        self._history.append(PoolTransaction(
            side='SELL',
            quantity=qty,
            amount=cost_basis,
            avg_cost_after=self.avg_cost,
            quantity_after=self._quantity,
            total_cost_after=self._total_cost,
        ))

        return cost_basis
