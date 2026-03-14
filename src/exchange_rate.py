"""Exchange rate fetching and caching module.

Architecture:
  RateProvider  — knows how to fetch rates from one external source.
  ExchangeRateManager — orchestrates cache, providers, and fallback logic.
"""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Dict, Optional

import requests

from .database import DatabaseManager


class RateSource(StrEnum):
    """Where the rate data actually came from."""
    FRANKFURTER = 'frankfurter'
    FALLBACK = 'fallback'


# ---------------------------------------------------------------------------
# Provider interface + implementations
# ---------------------------------------------------------------------------

class RateProvider(ABC):
    """Fetches exchange rates from a single external source."""

    @property
    @abstractmethod
    def source(self) -> RateSource:
        """Identifier stored in DB alongside the rate."""

    @abstractmethod
    def fetch(self, date: str, from_ccy: str, to_ccy: str) -> Optional[float]:
        """Return the rate for *date*, or None on miss."""

    @abstractmethod
    def fetch_series(self, start: str, end: str,
                     from_ccy: str, to_ccy: str) -> Optional[Dict[str, float]]:
        """Return {date: rate} for the range, or None on failure."""


class FrankfurterProvider(RateProvider):
    """ECB rates via frankfurter.dev (free, no key required)."""

    BASE_URL = 'https://api.frankfurter.dev/v1'

    @property
    def source(self) -> RateSource:
        return RateSource.FRANKFURTER

    def fetch(self, date: str, from_ccy: str, to_ccy: str) -> Optional[float]:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/{date}",
                params={'from': from_ccy, 'to': to_ccy},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get('rates', {}).get(to_ccy)
        except Exception:
            pass
        return None

    def fetch_series(self, start: str, end: str,
                     from_ccy: str, to_ccy: str) -> Optional[Dict[str, float]]:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/{start}..{end}",
                params={'from': from_ccy, 'to': to_ccy},
                timeout=30,
            )
            if resp.status_code == 200:
                return {
                    d: day[to_ccy]
                    for d, day in resp.json().get('rates', {}).items()
                    if to_ccy in day
                }
        except Exception as e:
            print(f"  Time series request failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class ExchangeRateManager:
    """Resolves exchange rates: cache → provider → nearby → fallback."""

    # Last-resort hardcoded rates (rough 2024 averages).
    _FALLBACK_CNY = {
        'USD': 7.2, 'HKD': 0.92, 'SGD': 5.35, 'EUR': 7.8, 'GBP': 9.1,
    }

    def __init__(self, db: DatabaseManager,
                 provider: RateProvider | None = None):
        self.db = db
        self.provider = provider or FrankfurterProvider()

    # -- public API ----------------------------------------------------------

    def get_rate(self, date: str, from_ccy: str, to_ccy: str = 'CNY') -> float:
        """Return the exchange rate, resolving from cache/provider/fallback."""
        cached = self.db.get_exchange_rate(date, from_ccy, to_ccy)
        if cached:
            return cached['rate']

        rate, source = self._resolve(date, from_ccy, to_ccy)
        if rate:
            self.db.save_exchange_rate(date, from_ccy, to_ccy, rate, source)
        return rate or 1.0

    def batch_fetch(self, dates: list, from_ccy: str,
                    to_ccy: str = 'CNY'):
        """Fetch rates for multiple dates, preferring a single time-series call."""
        if not dates:
            return

        uncached = [d for d in dates
                    if not self.db.get_exchange_rate(d, from_ccy, to_ccy)]
        if not uncached:
            print(f"All {len(dates)} rates already cached ({from_ccy} → {to_ccy})")
            return

        print(f"Fetching {len(uncached)} exchange rates ({from_ccy} → {to_ccy})...")

        series = self.provider.fetch_series(
            min(uncached), max(uncached), from_ccy, to_ccy)

        if series is not None:
            self._save_series(uncached, series, from_ccy, to_ccy)
        else:
            print("  Time series unavailable, fetching per-date...")
            for date in uncached:
                self.get_rate(date, from_ccy, to_ccy)
            print("  Done.")

    # -- internals -----------------------------------------------------------

    def _resolve(self, date: str, from_ccy: str,
                 to_ccy: str) -> tuple[Optional[float], str]:
        """Try provider → hardcoded fallback."""
        rate = self.provider.fetch(date, from_ccy, to_ccy)
        if rate:
            return rate, self.provider.source

        rate = self._fallback(from_ccy, to_ccy)
        if rate:
            print(f"  ⚠️  Using hardcoded fallback {rate} for "
                  f"{from_ccy}/{to_ccy} on {date}")
            return rate, RateSource.FALLBACK

        return None, RateSource.FALLBACK

    @classmethod
    def _fallback(cls, from_ccy: str, to_ccy: str) -> Optional[float]:
        if to_ccy == 'CNY':
            return cls._FALLBACK_CNY.get(from_ccy)
        return None

    def _save_series(self, uncached: list, series: dict,
                     from_ccy: str, to_ccy: str):
        sorted_series_dates = sorted(series.keys())
        saved = 0
        for date in uncached:
            rate = series.get(date) or self._nearest_before(date, sorted_series_dates, series)
            if rate:
                self.db.save_exchange_rate(
                    date, from_ccy, to_ccy, rate, self.provider.source)
                saved += 1
            else:
                print(f"  ⚠️  No rate available for {date} — skipped")
        print(f"  Done — saved {saved}/{len(uncached)} rates")

    @staticmethod
    def _nearest_before(date: str, sorted_dates: list, series: dict) -> Optional[float]:
        """Find the most recent rate on or before *date* from the series."""
        for d in reversed(sorted_dates):
            if d <= date:
                return series[d]
        return None
