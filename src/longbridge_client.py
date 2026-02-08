"""Long Bridge API client for fetching trading data (READ-ONLY)."""

from longport.openapi import TradeContext, Config as LongportConfig, OrderStatus
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time

class LongBridgeClient:
    """Client for Long Bridge OpenAPI (read-only operations)."""
    
    def __init__(self, app_key: str, app_secret: str, access_token: str):
        self.config = LongportConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=access_token
        )
        self.ctx = TradeContext(self.config)
    
    def fetch_orders(self, start: datetime, end: datetime) -> List[Dict]:
        """
        Fetch historical filled orders for a date range.
        Handles 90-day API limit by chunking requests.
        """
        print(f"Fetching orders from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}...")

        orders = []
        chunk_start = start
        chunk_num = 1

        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=89), end)

            print(f"  Chunk {chunk_num}: {chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}")

            try:
                result = self.ctx.history_orders(
                    status=[OrderStatus.Filled],
                    start_at=chunk_start,
                    end_at=chunk_end
                )

                count = len(result) if result else 0
                print(f"    Found {count} orders")

                if result:
                    for order in result:
                        parsed = self._parse_order(order)
                        if parsed:
                            orders.append(parsed)

            except Exception as e:
                print(f"    Error: {e}")

            chunk_start = chunk_end + timedelta(days=1)
            chunk_num += 1
            time.sleep(0.5)

        print(f"Total: {len(orders)} orders fetched")
        return orders
    
    def _parse_order(self, order) -> Optional[Dict]:
        """Parse Long Bridge order object to dictionary."""
        try:
            # Skip non-executed orders
            qty = float(getattr(order, 'executed_quantity', 0) or 0)
            if qty <= 0:
                return None
            
            # Get price
            price = float(getattr(order, 'executed_price', 0) or 0)
            if price <= 0:
                last_done = getattr(order, 'last_done', None)
                if last_done:
                    try:
                        price = float(last_done)
                    except:
                        pass
            
            if price <= 0:
                return None
            
            # Parse side
            side_raw = getattr(order, 'side', None)
            if not side_raw:
                return None
            
            side_str = getattr(side_raw, 'name', None) or str(side_raw)
            side = 'BUY' if 'BUY' in side_str.upper() else 'SELL' if 'SELL' in side_str.upper() else None
            if not side:
                return None
            
            # Parse timestamp
            ts = getattr(order, 'updated_at', None) or getattr(order, 'submitted_at', None)
            if isinstance(ts, str):
                executed_at = datetime.fromtimestamp(int(ts)).isoformat()
            elif isinstance(ts, (int, float)):
                executed_at = datetime.fromtimestamp(ts).isoformat()
            elif hasattr(ts, 'isoformat'):
                executed_at = ts.isoformat()
            else:
                executed_at = datetime.now().isoformat()
            
            symbol = str(getattr(order, 'symbol', ''))
            currency = str(getattr(order, 'currency', '') or self._infer_currency(symbol)).upper()
            
            return {
                'order_id': str(order.order_id),
                'symbol': symbol,
                'side': side,
                'quantity': qty,
                'price': price,
                'executed_at': executed_at,
                'currency': currency,
                'fees': {}
            }
        except Exception as e:
            print(f"  Error parsing order: {e}")
            return None
    
    def _infer_currency(self, symbol: str) -> str:
        """Infer currency from symbol suffix."""
        s = symbol.upper()
        if '.HK' in s:
            return 'HKD'
        elif '.SG' in s:
            return 'SGD'
        return 'USD'
    
    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            self.ctx.account_balance()
            print("✓ Long Bridge API connection successful")
            return True
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False