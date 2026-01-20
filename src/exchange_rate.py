"""Exchange rate fetching and caching module."""

import requests
from datetime import datetime, timedelta
from typing import Optional
from .database import DatabaseManager

class ExchangeRateManager:
    """Manages exchange rate fetching and caching."""
    
    # 2024 average rates for CNY (fallback values)
    CNY_RATES = {
        'USD': 7.2,
        'HKD': 0.92,
        'SGD': 5.35,
        'EUR': 7.8,
        'GBP': 9.1,
    }
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def get_rate(self, date: str, from_currency: str, to_currency: str = "CNY") -> float:
        """
        Get exchange rate for a specific date.
        Returns cached rate, fetches from API, or uses fallback.
        """
        # Check cache first
        cached = self.db.get_exchange_rate(date, from_currency, to_currency)
        if cached:
            return cached
        
        # Try to fetch from API
        rate = self._fetch_rate(date, from_currency, to_currency)
        
        if not rate:
            # Try nearby dates
            rate = self._get_nearby_rate(date, from_currency, to_currency)
        
        if not rate:
            # Use fallback
            rate = self._get_fallback_rate(from_currency, to_currency)
            if rate:
                print(f"  Using fallback rate {rate} for {from_currency}/{to_currency}")
        
        # Cache the rate
        if rate:
            self.db.save_exchange_rate(date, from_currency, to_currency, rate)
        
        return rate or 1.0
    
    def _fetch_rate(self, date: str, from_currency: str, to_currency: str) -> Optional[float]:
        """Fetch rate from external API."""
        # Try frankfurter.app (free, no API key)
        try:
            url = f"https://api.frankfurter.app/{date}?from={from_currency}&to={to_currency}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if 'rates' in data and to_currency in data['rates']:
                    return data['rates'][to_currency]
        except:
            pass
        
        # For CNY, use calculated rates (most free APIs don't support CNY well)
        if to_currency == 'CNY' and from_currency in self.CNY_RATES:
            return self.CNY_RATES[from_currency]
        
        return None
    
    def _get_nearby_rate(self, date: str, from_currency: str, to_currency: str) -> Optional[float]:
        """Get rate from nearby cached dates."""
        target = datetime.strptime(date, '%Y-%m-%d')
        
        for offset in range(1, 8):
            for direction in [-1, 1]:
                check_date = (target + timedelta(days=offset * direction)).strftime('%Y-%m-%d')
                rate = self.db.get_exchange_rate(check_date, from_currency, to_currency)
                if rate:
                    return rate
        return None
    
    def _get_fallback_rate(self, from_currency: str, to_currency: str) -> Optional[float]:
        """Get fallback rate for common pairs."""
        if to_currency == 'CNY':
            return self.CNY_RATES.get(from_currency)
        return None
    
    def batch_fetch(self, dates: list, from_currency: str, to_currency: str = "CNY"):
        """Batch fetch exchange rates for multiple dates."""
        print(f"Fetching exchange rates for {len(dates)} dates ({from_currency} -> {to_currency})...")
        
        for i, date in enumerate(dates):
            if i > 0 and i % 10 == 0:
                print(f"  Progress: {i}/{len(dates)}")
            self.get_rate(date, from_currency, to_currency)
        
        print(f"  Done.")