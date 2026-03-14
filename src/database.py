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
                    source TEXT NOT NULL DEFAULT 'unknown',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (date, from_currency, to_currency)
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS dividends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    amount REAL NOT NULL,
                    withholding REAL NOT NULL DEFAULT 0,
                    received_at TEXT NOT NULL,
                    flow_name TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, received_at, amount)
                )
            ''')
            # Migrate: add source column if missing (existing databases)
            cursor = conn.execute("PRAGMA table_info(exchange_rates)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'source' not in columns:
                conn.execute("ALTER TABLE exchange_rates ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown'")

            # Migrate: add withholding column to dividends if missing
            cursor = conn.execute("PRAGMA table_info(dividends)")
            columns = [row[1] for row in cursor.fetchall()]
            if columns and 'withholding' not in columns:
                conn.execute("ALTER TABLE dividends ADD COLUMN withholding REAL NOT NULL DEFAULT 0")

    def save_orders(self, orders: List[Dict]):
        """Save trading orders to database (batch insert)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany('''
                INSERT OR REPLACE INTO orders
                (order_id, symbol, side, quantity, price, currency, executed_at, fees_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (o['order_id'], o['symbol'], o['side'], o['quantity'],
                 o['price'], o['currency'], o['executed_at'],
                 json.dumps(o.get('fees', {})))
                for o in orders
            ])

    def get_symbols_with_sells(self, year: int) -> List[str]:
        """Get symbols that have SELL orders in a specific year."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT DISTINCT symbol FROM orders
                WHERE strftime('%Y', executed_at) = ? AND side = 'SELL'
                ORDER BY symbol
            ''', (str(year),))
            return [row[0] for row in cursor.fetchall()]

    def get_orders_until(self, symbol: str, end_year: int) -> List[Dict]:
        """Get all orders for a symbol from earliest record up to end of end_year.

        Returns orders sorted by executed_at ascending.
        This is the data source for building a complete cost pool.
        """
        end_date = f"{end_year}-12-31T23:59:59"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM orders
                WHERE symbol = ? AND executed_at <= ?
                ORDER BY executed_at
            ''', (symbol, end_date))

            return [self._row_to_order(row) for row in cursor.fetchall()]

    def save_exchange_rate(self, date: str, from_currency: str, to_currency: str,
                          rate: float, source: str = 'unknown'):
        """Save exchange rate to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO exchange_rates
                (date, from_currency, to_currency, rate, source)
                VALUES (?, ?, ?, ?, ?)
            ''', (date, from_currency, to_currency, rate, source))

    def get_exchange_rate(self, date: str, from_currency: str,
                          to_currency: str) -> Optional[Dict]:
        """Get exchange rate from database. Returns dict with 'rate' and 'source', or None."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT rate, source FROM exchange_rates
                WHERE date = ? AND from_currency = ? AND to_currency = ?
            ''', (date, from_currency, to_currency))
            result = cursor.fetchone()
            return {'rate': result[0], 'source': result[1]} if result else None

    def clear_year_data(self, year: int):
        """Clear all data for a specific year."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM orders WHERE strftime('%Y', executed_at) = ?", (str(year),))
            conn.execute("DELETE FROM exchange_rates WHERE strftime('%Y', date) = ?", (str(year),))

    def update_order_fees(self, order_id: str, fees: Dict):
        """Update only the fees_json field for an existing order."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE orders SET fees_json = ? WHERE order_id = ?",
                (json.dumps(fees), order_id)
            )

    def get_orders_missing_fees(self, year: int = None) -> List[Dict]:
        """Get orders that have no fee data yet.

        Returns order_id list for orders where fees_json is null, empty, or '{}'.
        """
        query = '''
            SELECT order_id, symbol FROM orders
            WHERE (fees_json IS NULL OR fees_json = '' OR fees_json = '{}')
        '''
        params = []
        if year:
            query += " AND strftime('%Y', executed_at) = ?"
            params.append(str(year))
        query += " ORDER BY executed_at"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def get_fallback_rate_count(self, year: int = None) -> int:
        """Count exchange rates that used fallback (hardcoded) source."""
        query = "SELECT COUNT(*) FROM exchange_rates WHERE source = 'fallback'"
        params = []
        if year:
            query += " AND strftime('%Y', date) = ?"
            params.append(str(year))
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(query, params).fetchone()[0]


    def save_dividends(self, dividends: List[Dict]):
        """Save dividend records (skip duplicates)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany('''
                INSERT OR IGNORE INTO dividends
                (symbol, currency, amount, withholding, received_at, flow_name, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', [
                (d['symbol'], d['currency'], d['amount'], d.get('withholding', 0),
                 d['received_at'], d['flow_name'], d.get('description', ''))
                for d in dividends
            ])

    def get_dividends(self, year: int) -> List[Dict]:
        """Get all dividend records for a year."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM dividends
                WHERE strftime('%Y', received_at) = ?
                ORDER BY received_at
            ''', (str(year),))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> Dict:
        """Convert a database row to an order dict."""
        order = dict(row)
        order['fees'] = json.loads(order['fees_json'] or '{}')
        del order['fees_json']
        return order
