"""Tax calculation engine — orchestrates settlement and cost pool modules.

This module does NOT perform any exchange rate, fee, or cost calculations itself.
It delegates to SettlementCalculator and CostPool, then assembles the tax report.
"""

from typing import Dict
from datetime import datetime
from pathlib import Path
from .database import DatabaseManager
from .settlement import SettlementCalculator
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

    def export_csv(self, results: Dict, output_dir: Path) -> Path:
        """Export combined tax report to a single CSV file.

        Layout:
          1. Transaction details (each sell/close)
          2. Blank separator
          3. Per-symbol summary
          4. Blank separator
          5. Totals including net gains and tax owed
        """
        import csv

        output_dir.mkdir(exist_ok=True)
        year = results['year']
        report_path = output_dir / f'tax_report_{year}.csv'

        with open(report_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)

            # --- Section 1: Transaction Details ---
            detail_cols = [
                'order_id', 'symbol', 'date', 'quantity', 'price',
                'currency', 'rate', 'proceeds_cny', 'cost_basis_cny',
                'gain_loss', 'tax',
            ]
            writer.writerow(['[ Transaction Details ]'])
            writer.writerow(detail_cols)
            for tx in results['details']:
                writer.writerow([tx[c] for c in detail_cols])

            # --- Separator ---
            writer.writerow([])

            # --- Section 2: Per-Symbol Summary ---
            summary_cols = [
                'Symbol', 'Gains (CNY)', 'Losses (CNY)',
                'Net (CNY)', 'Remaining Qty', 'Remaining Cost (CNY)',
            ]
            writer.writerow(['[ Per-Symbol Summary ]'])
            writer.writerow(summary_cols)
            for sym, s in results['summary'].items():
                writer.writerow([
                    sym, f"{s['gains']:.2f}", f"{s['losses']:.2f}",
                    f"{s['gains'] - s['losses']:.2f}",
                    s['remaining_qty'], f"{s['remaining_cost']:.2f}",
                ])

            # --- Separator ---
            writer.writerow([])

            # --- Section 3: Totals ---
            writer.writerow(['[ Totals ]'])
            writer.writerow(['Item', 'Amount (CNY)'])
            writer.writerow(['Total Gains', f"{results['total_gains']:.2f}"])
            writer.writerow(['Total Losses', f"{results['total_losses']:.2f}"])
            writer.writerow(['Net Gains', f"{results['net_gains']:.2f}"])
            tax_pct = f"{self.tax_rate * 100:.0f}%"
            writer.writerow([f'Tax Rate', tax_pct])
            writer.writerow(['Tax Owed', f"{results['total_tax']:.2f}"])

        print(f"Exported: {report_path}")
        return report_path

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
        return {
            'order_id': order['order_id'],
            'symbol': order['symbol'],
            'date': self._parse_date(order['executed_at']),
            'quantity': order['quantity'],
            'price': order['price'],
            'currency': order['currency'],
            'rate': rate,
            'proceeds_cny': proceeds_cny,
            'cost_basis_cny': cost_basis_cny,
            'gain_loss': gain_loss,
            'tax': max(0, gain_loss) * self.tax_rate,
        }


    @staticmethod
    def _in_year(order: Dict, year: int) -> bool:
        return datetime.fromisoformat(order['executed_at']).year == year

    @staticmethod
    def _parse_date(executed_at: str) -> str:
        return datetime.fromisoformat(executed_at).strftime('%Y-%m-%d')
