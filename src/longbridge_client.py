"""Long Bridge API client for fetching trading data (READ-ONLY)."""

import os
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from longport.openapi import (
    BalanceType,
    Config as LongportConfig,
    OrderStatus,
    TradeContext,
)

# Long Bridge API enforces a ~90-day window per request.
_CHUNK_DAYS = 89


class LongBridgeClient:
    """Client for Long Bridge OpenAPI (read-only operations)."""

    def __init__(self, app_key: str, app_secret: str, access_token: str):
        # Populate LONGPORT_* env vars so Config.from_env() picks them up,
        # along with LONGPORT_REGION if set (e.g. "cn" for China endpoint).
        os.environ.setdefault('LONGPORT_APP_KEY', app_key)
        os.environ.setdefault('LONGPORT_APP_SECRET', app_secret)
        os.environ.setdefault('LONGPORT_ACCESS_TOKEN', access_token)
        self.config = LongportConfig.from_env()
        self.ctx = TradeContext(self.config)

    # -- chunked fetch helper ------------------------------------------------

    @staticmethod
    def _chunked_fetch(start: datetime, end: datetime,
                       fetch_fn: Callable[[datetime, datetime], List],
                       label: str = 'items',
                       delay: float = 0.5) -> List:
        """Split a date range into 90-day chunks and collect results.

        Args:
            fetch_fn: Called with (chunk_start, chunk_end), returns a list.
            label: Name shown in progress logs.
            delay: Seconds to sleep between chunks.
        """
        print(f"Fetching {label} from {start.strftime('%Y-%m-%d')} "
              f"to {end.strftime('%Y-%m-%d')}...")

        all_items: List = []
        chunk_start = start
        chunk_num = 1

        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS), end)
            print(f"  Chunk {chunk_num}: {chunk_start.strftime('%Y-%m-%d')} "
                  f"to {chunk_end.strftime('%Y-%m-%d')}")

            try:
                items = fetch_fn(chunk_start, chunk_end)
                print(f"    Found {len(items)} {label}")
                all_items.extend(items)
            except Exception as e:
                print(f"    Error: {e}")

            chunk_start = chunk_end + timedelta(days=1)
            chunk_num += 1
            time.sleep(delay)

        print(f"Total: {len(all_items)} {label} fetched")
        return all_items

    # -- orders --------------------------------------------------------------

    def fetch_orders(self, start: datetime, end: datetime) -> List[Dict]:
        """Fetch historical filled orders, chunked into 90-day windows."""
        return self._chunked_fetch(
            start, end, self._fetch_orders_chunk, label='orders')

    def _fetch_orders_chunk(self, start: datetime, end: datetime) -> List[Dict]:
        result = self.ctx.history_orders(
            status=[OrderStatus.Filled],
            start_at=start,
            end_at=end,
        )
        if not result:
            return []
        return [p for p in (self._parse_order(o) for o in result) if p]
    
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
                    except (ValueError, TypeError):
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

    def fetch_order_detail(self, order_id: str) -> Optional[Dict]:
        """Fetch charge_detail for a single order via order detail API.

        Returns:
            Dict with 'total_amount' and 'currency', or None on failure.
        """
        try:
            detail = self.ctx.order_detail(order_id=order_id)
            charge = getattr(detail, 'charge_detail', None)
            if not charge:
                return None

            total = str(getattr(charge, 'total_amount', '0'))
            currency = str(getattr(charge, 'currency', ''))
            items = []

            for item in getattr(charge, 'items', []):
                for fee in getattr(item, 'fees', []):
                    items.append({
                        'code': str(getattr(fee, 'code', '')),
                        'name': str(getattr(fee, 'name', '')),
                        'amount': str(getattr(fee, 'amount', '0')),
                        'currency': str(getattr(fee, 'currency', '')),
                    })

            return {
                'total_amount': str(total),
                'currency': str(currency),
                'items': items,
            }
        except Exception as e:
            print(f"  Error fetching detail for {order_id}: {e}")
            return None


    def fetch_cashflow(self, start: datetime, end: datetime,
                       business_type: Optional[BalanceType] = None) -> List[Dict]:
        """Fetch account cash flow entries, chunked into 90-day windows."""
        return self._chunked_fetch(
            start, end,
            lambda s, e: self._fetch_cashflow_chunk(s, e, business_type),
            label='cash flow entries',
            delay=0.3,
        )

    def _fetch_cashflow_chunk(self, start: datetime, end: datetime,
                              business_type: Optional[BalanceType]) -> List[Dict]:
        """Fetch one chunk of cash flow, handling pagination."""
        entries: List[Dict] = []
        page = 1
        while True:
            result = self.ctx.cash_flow(
                start_at=start,
                end_at=end,
                business_type=business_type,
                page=page,
                size=1000,
            )
            if not result:
                break
            for entry in result:
                parsed = self._parse_cashflow(entry)
                if parsed:
                    entries.append(parsed)
            if len(result) < 1000:
                break
            page += 1
            time.sleep(0.3)
        return entries

    @staticmethod
    def _parse_cashflow(entry) -> Optional[Dict]:
        """Parse a CashFlow SDK object to dict."""
        try:
            # The SDK's CashFlowDirection enum is not exported from the
            # top-level `longport.openapi` namespace, so we can't do
            # isinstance checks.  Inspecting the class name is the most
            # reliable workaround.
            direction_name = type(entry.direction).__name__
            if direction_name == 'In':
                direction = 'IN'
            elif direction_name == 'Out':
                direction = 'OUT'
            else:
                direction = 'UNKNOWN'

            ts = entry.business_time
            if hasattr(ts, 'isoformat'):
                business_time = ts.isoformat()
            elif isinstance(ts, (int, float)):
                business_time = datetime.fromtimestamp(ts).isoformat()
            else:
                business_time = str(ts)

            return {
                'transaction_flow_name': str(entry.transaction_flow_name),
                'direction': direction,
                'balance': float(entry.balance),
                'currency': str(entry.currency),
                'business_time': business_time,
                'symbol': str(entry.symbol) if entry.symbol else None,
                'description': str(entry.description) if entry.description else '',
            }
        except Exception as e:
            print(f"  Error parsing cash flow entry: {e}")
            return None

