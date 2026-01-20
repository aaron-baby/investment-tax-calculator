"""Tax calculation engine following Chinese capital gains tax rules."""

from typing import List, Dict
from datetime import datetime
from pathlib import Path
import pandas as pd
from .database import DatabaseManager
from .exchange_rate import ExchangeRateManager

class TaxCalculator:
    """Calculate capital gains tax using weighted average cost method."""
    
    def __init__(self, db: DatabaseManager, exchange: ExchangeRateManager, tax_rate: float = 0.20):
        self.db = db
        self.exchange = exchange
        self.tax_rate = tax_rate
    
    def calculate(self, year: int) -> Dict:
        """Calculate capital gains tax for a specific year."""
        print(f"Calculating capital gains tax for {year}...")
        
        orders = self.db.get_orders_by_year(year)
        if not orders:
            return {'year': year, 'total_tax': 0, 'details': [], 'summary': {}}
        
        symbols = self.db.get_symbols_by_year(year)
        
        results = {
            'year': year,
            'total_gains': 0,
            'total_losses': 0,
            'net_gains': 0,
            'total_tax': 0,
            'details': [],
            'summary': {}
        }
        
        for symbol in symbols:
            symbol_result = self._calculate_symbol(symbol, orders)
            results['details'].extend(symbol_result['transactions'])
            results['summary'][symbol] = symbol_result['summary']
            
            results['total_gains'] += symbol_result['summary']['gains']
            results['total_losses'] += symbol_result['summary']['losses']
        
        results['net_gains'] = max(0, results['total_gains'] - results['total_losses'])
        results['total_tax'] = results['net_gains'] * self.tax_rate
        
        print(f"Net gains: ¥{results['net_gains']:,.2f}, Tax: ¥{results['total_tax']:,.2f}")
        return results
    
    def _calculate_symbol(self, symbol: str, all_orders: List[Dict]) -> Dict:
        """Calculate tax for a specific symbol using weighted average cost."""
        orders = sorted(
            [o for o in all_orders if o['symbol'] == symbol],
            key=lambda x: x['executed_at']
        )
        
        buys = [o for o in orders if o['side'] == 'BUY']
        sells = [o for o in orders if o['side'] == 'SELL']
        
        if not sells:
            return {'transactions': [], 'summary': {'symbol': symbol, 'gains': 0, 'losses': 0}}
        
        # Build cost pool in CNY
        cost_pool = self._build_cost_pool(buys)
        
        # Calculate gains/losses for sells
        transactions = []
        total_gains = 0
        total_losses = 0
        
        for sell in sells:
            tx = self._calculate_transaction(sell, cost_pool)
            transactions.append(tx)
            
            if tx['gain_loss'] > 0:
                total_gains += tx['gain_loss']
            else:
                total_losses += abs(tx['gain_loss'])
        
        return {
            'transactions': transactions,
            'summary': {'symbol': symbol, 'gains': total_gains, 'losses': total_losses}
        }
    
    def _build_cost_pool(self, buys: List[Dict]) -> Dict:
        """Build weighted average cost pool in CNY."""
        total_qty = 0
        total_cost_cny = 0
        
        for buy in buys:
            date = datetime.fromisoformat(buy['executed_at']).strftime('%Y-%m-%d')
            rate = self.exchange.get_rate(date, buy['currency'], 'CNY')
            
            cost = buy['quantity'] * buy['price'] * rate
            total_qty += buy['quantity']
            total_cost_cny += cost
        
        avg_cost = total_cost_cny / total_qty if total_qty > 0 else 0
        
        return {
            'total_qty': total_qty,
            'total_cost_cny': total_cost_cny,
            'avg_cost_per_share': avg_cost
        }
    
    def _calculate_transaction(self, sell: Dict, cost_pool: Dict) -> Dict:
        """Calculate gain/loss for a single sell transaction."""
        date = datetime.fromisoformat(sell['executed_at']).strftime('%Y-%m-%d')
        rate = self.exchange.get_rate(date, sell['currency'], 'CNY')
        
        proceeds_cny = sell['quantity'] * sell['price'] * rate
        cost_basis_cny = sell['quantity'] * cost_pool['avg_cost_per_share']
        gain_loss = proceeds_cny - cost_basis_cny
        
        return {
            'order_id': sell['order_id'],
            'symbol': sell['symbol'],
            'date': date,
            'quantity': sell['quantity'],
            'price': sell['price'],
            'currency': sell['currency'],
            'rate': rate,
            'proceeds_cny': proceeds_cny,
            'cost_basis_cny': cost_basis_cny,
            'gain_loss': gain_loss,
            'tax': max(0, gain_loss) * self.tax_rate
        }
    
    def export_csv(self, results: Dict, output_dir: Path) -> Path:
        """Export results to CSV files."""
        output_dir.mkdir(exist_ok=True)
        year = results['year']
        
        # Detail CSV
        if results['details']:
            df = pd.DataFrame(results['details'])
            detail_path = output_dir / f'tax_detail_{year}.csv'
            df.to_csv(detail_path, index=False, encoding='utf-8-sig')
            print(f"Exported: {detail_path}")
        
        # Summary CSV
        summary_data = [
            {'Symbol': sym, 'Gains (CNY)': s['gains'], 'Losses (CNY)': s['losses']}
            for sym, s in results['summary'].items()
        ]
        summary_data.append({
            'Symbol': 'TOTAL',
            'Gains (CNY)': results['total_gains'],
            'Losses (CNY)': results['total_losses']
        })
        
        summary_path = output_dir / f'tax_summary_{year}.csv'
        pd.DataFrame(summary_data).to_csv(summary_path, index=False, encoding='utf-8-sig')
        print(f"Exported: {summary_path}")
        
        return summary_path