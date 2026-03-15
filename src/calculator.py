"""Tax calculation engine — orchestrates settlement and cost pool modules.

This module does NOT perform any exchange rate, fee, or cost calculations itself.
It delegates to SettlementCalculator and CostPool, then assembles the results.
"""

from typing import Dict
from datetime import datetime
from .database import DatabaseManager
from .settlement import SettlementCalculator, parse_option_expiry
from .cost_pool import CostPool


class TaxCalculator:
    """Orchestrates capital gains tax calculation."""

    def __init__(self, db: DatabaseManager, settlement: SettlementCalculator,
                 tax_rate: float = 0.20):
        self.db = db
        self.settlement = settlement
        self.tax_rate = tax_rate

    def calculate(self, year: int) -> Dict:
        """Calculate capital gains tax for a specific year."""
        print(f"Calculating capital gains tax for {year}...")

        symbols = self.db.get_symbols_with_sells(year)
        if not symbols:
            return self._empty_result(year)

        results = self._empty_result(year)

        for symbol in symbols:
            symbol_result = self._process_symbol(symbol, year)
            results['details'].extend(symbol_result['transactions'])
            results['summary'][symbol] = symbol_result['summary']
            results['total_gains'] += symbol_result['summary']['gains']
            results['total_losses'] += symbol_result['summary']['losses']

        results['net_gains'] = max(0, results['total_gains'] - results['total_losses'])
        results['total_tax'] = results['net_gains'] * self.tax_rate

        print(f"Net gains: ¥{results['net_gains']:,.2f}, Tax: ¥{results['total_tax']:,.2f}")
        return results

    def _process_symbol(self, symbol: str, year: int) -> Dict:
        """Process a single symbol: replay history through cost pool, collect year's sells."""
        orders = self.db.get_orders_until(symbol, year)
        pool = CostPool(symbol)

        transactions = []
        total_gains = 0
        total_losses = 0

        for order in orders:
            in_year = self._in_year(order, year)

            if order['side'] == 'BUY':
                settled_cost = self.settlement.settle_buy(order)
                cost_basis = pool.buy(order['quantity'], settled_cost)

                # cost_basis > 0 means closing a short position (buy-to-close)
                if cost_basis > 0 and in_year:
                    # For short close: proceeds were locked in at open, cost is what we pay now
                    proceeds_cny = cost_basis   # the proceeds received when opening short
                    cost_cny = settled_cost      # what we pay to close
                    gain_loss = proceeds_cny - cost_cny
                    rate = self.settlement.get_rate_for_order(order)
                    tx = self._build_tx(order, rate, proceeds_cny, cost_cny, gain_loss)
                    transactions.append(tx)
                    if gain_loss > 0:
                        total_gains += gain_loss
                    else:
                        total_losses += abs(gain_loss)

            elif order['side'] == 'SELL':
                # Need settled_amount for potential sell-to-open
                proceeds_cny, rate = self.settlement.settle_sell_with_rate(order)
                cost_basis = pool.sell(order['quantity'], settled_amount=proceeds_cny)

                # cost_basis > 0 means closing a long position
                if cost_basis > 0 and in_year:
                    gain_loss = proceeds_cny - cost_basis
                    tx = self._build_tx(order, rate, proceeds_cny, cost_basis, gain_loss)
                    transactions.append(tx)
                    if gain_loss > 0:
                        total_gains += gain_loss
                    else:
                        total_losses += abs(gain_loss)

                # cost_basis == 0 means sell-to-open (short), no taxable event yet

        # Handle expired options still in the pool at year-end.
        # Option symbols encode their expiry date (YYMMDD).
        # - Short expired: full proceeds become profit (buy-to-close at 0).
        # - Long expired: entire cost basis becomes a loss (sell-to-close at 0).
        expiry = parse_option_expiry(symbol)
        if expiry and expiry.year <= year and (pool.is_short or pool.is_long):
            expired_qty = abs(pool.quantity)

            if pool.is_short:
                locked_proceeds = pool.buy(expired_qty, 0)
                gain_loss = locked_proceeds
                tx = self._build_expiry_tx(symbol, expiry, expired_qty,
                                           proceeds_cny=locked_proceeds,
                                           cost_cny=0)
            else:
                # sell() on a long position returns cost_basis, ignores settled_amount
                cost_basis = pool.sell(expired_qty, settled_amount=0)
                gain_loss = -cost_basis
                tx = self._build_expiry_tx(symbol, expiry, expired_qty,
                                           proceeds_cny=0,
                                           cost_cny=cost_basis)

            transactions.append(tx)
            if gain_loss > 0:
                total_gains += gain_loss
            else:
                total_losses += abs(gain_loss)

        return {
            'transactions': transactions,
            'summary': {
                'symbol': symbol,
                'gains': total_gains,
                'losses': total_losses,
                'remaining_qty': pool.quantity,
                'remaining_cost': pool.total_cost,
            }
        }


    @staticmethod
    def _empty_result(year: int) -> Dict:
        return {
            'year': year,
            'total_gains': 0,
            'total_losses': 0,
            'net_gains': 0,
            'total_tax': 0,
            'details': [],
            'summary': {},
        }

    def _build_tx(self, order: Dict, rate: float, proceeds_cny: float,
                  cost_basis_cny: float, gain_loss: float) -> Dict:
        fee_original = SettlementCalculator._extract_fees(order)
        return {
            'order_id': order['order_id'],
            'symbol': order['symbol'],
            'date': self._parse_date(order['executed_at']),
            'quantity': order['quantity'],
            'price': order['price'],
            'currency': order['currency'],
            'commission_fee': fee_original,
            'rate': rate,
            'proceeds_cny': proceeds_cny,
            'cost_basis_cny': cost_basis_cny,
            'gain_loss': gain_loss,
        }

    @staticmethod
    def _build_expiry_tx(symbol: str, expiry: datetime, quantity: float,
                         proceeds_cny: float, cost_cny: float) -> Dict:
        """Build a synthetic transaction for an expired option."""
        return {
            'order_id': f'EXPIRED-{symbol}',
            'symbol': symbol,
            'date': expiry.strftime('%Y-%m-%d'),
            'quantity': quantity,
            'price': 0,
            'currency': '',
            'commission_fee': 0,
            'rate': 0,
            'proceeds_cny': proceeds_cny,
            'cost_basis_cny': cost_cny,
            'gain_loss': proceeds_cny - cost_cny,
        }


    @staticmethod
    def _in_year(order: Dict, year: int) -> bool:
        return datetime.fromisoformat(order['executed_at']).year == year

    @staticmethod
    def _parse_date(executed_at: str) -> str:
        return datetime.fromisoformat(executed_at).strftime('%Y-%m-%d')
