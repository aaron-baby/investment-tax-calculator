"""Database operations for storing trading data and exchange rates."""

import sqlite3
import json
from typing import List, Dict, Optional
from pathlib import Path

class DatabaseManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables."""
        self.db_path.parent.mkdir(exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    currency TEXT NOT NULL,
                    executed_at TEXT NOT NULL,
                    fees_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS exchange_rates (
                    date TEXT NOT NULL,
                    from_currency TEXT NOT NULL,
                    to_currency TEXT NOT NULL,
                    rate REAL NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (date, from_currency, to_currency)
                )
            ''')
    
    def save_orders(self, orders: List[Dict]):
        """Save trading orders to database."""
        with sqlite3.connect(self.db_path) as conn:
            for order in orders:
                conn.execute('''
                    INSERT OR REPLACE INTO orders 
                    (order_id, symbol, side, quantity, price, currency, executed_at, fees_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    order['order_id'],
                    order['symbol'],
                    order['side'],
                    order['quantity'],
                    order['price'],
                    order['currency'],
                    order['executed_at'],
                    json.dumps(order.get('fees', {}))
                ))
    
    def get_orders_by_year(self, year: int) -> List[Dict]:
        """Get all orders for a specific tax year."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM orders 
                WHERE strftime('%Y', executed_at) = ?
                ORDER BY executed_at
            ''', (str(year),))
            
            orders = []
            for row in cursor.fetchall():
                order = dict(row)
                order['fees'] = json.loads(order['fees_json'] or '{}')
                del order['fees_json']
                orders.append(order)
            
            return orders
    
    def get_symbols_by_year(self, year: int) -> List[str]:
        """Get unique symbols traded in a specific year."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT DISTINCT symbol FROM orders 
                WHERE strftime('%Y', executed_at) = ?
                ORDER BY symbol
            ''', (str(year),))
            return [row[0] for row in cursor.fetchall()]
    
    def save_exchange_rate(self, date: str, from_currency: str, to_currency: str, rate: float):
        """Save exchange rate to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO exchange_rates 
                (date, from_currency, to_currency, rate)
                VALUES (?, ?, ?, ?)
            ''', (date, from_currency, to_currency, rate))
    
    def get_exchange_rate(self, date: str, from_currency: str, to_currency: str) -> Optional[float]:
        """Get exchange rate from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT rate FROM exchange_rates 
                WHERE date = ? AND from_currency = ? AND to_currency = ?
            ''', (date, from_currency, to_currency))
            result = cursor.fetchone()
            return result[0] if result else None
    
    def clear_year_data(self, year: int):
        """Clear all data for a specific year."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM orders WHERE strftime('%Y', executed_at) = ?", (str(year),))
            conn.execute("DELETE FROM exchange_rates WHERE strftime('%Y', date) = ?", (str(year),))