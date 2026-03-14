"""Unit tests for ExchangeRateManager — source tracking, caching, batch fetch."""

import pytest
from unittest.mock import MagicMock
from src.database import DatabaseManager
from src.exchange_rate import (
    ExchangeRateManager, FrankfurterProvider, RateSource,
)


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(tmp_path / 'test.db')


@pytest.fixture
def provider():
    """A mock provider whose .source returns FRANKFURTER."""
    p = MagicMock(spec=FrankfurterProvider)
    p.source = RateSource.FRANKFURTER
    p.fetch.return_value = None
    p.fetch_series.return_value = None
    return p


@pytest.fixture
def manager(db, provider):
    return ExchangeRateManager(db, provider)


# --- Source tracking ---

class TestSourceTracking:
    def test_provider_rate_saved_with_provider_source(self, db, manager, provider):
        provider.fetch.return_value = 7.25
        rate = manager.get_rate('2024-06-15', 'USD', 'CNY')
        assert rate == 7.25
        cached = db.get_exchange_rate('2024-06-15', 'USD', 'CNY')
        assert cached == {'rate': 7.25, 'source': 'frankfurter'}

    def test_fallback_rate_saved_with_fallback_source(self, db, manager):
        rate = manager.get_rate('2024-06-15', 'USD', 'CNY')
        assert rate == 7.2
        cached = db.get_exchange_rate('2024-06-15', 'USD', 'CNY')
        assert cached['source'] == 'fallback'

    def test_cached_rate_skips_provider(self, db, manager, provider):
        db.save_exchange_rate('2024-06-15', 'USD', 'CNY', 7.30, RateSource.FRANKFURTER)
        rate = manager.get_rate('2024-06-15', 'USD', 'CNY')
        assert rate == 7.30
        provider.fetch.assert_not_called()


# --- Fallback behavior ---

class TestFallback:
    def test_known_currency(self):
        assert ExchangeRateManager._fallback('USD', 'CNY') == 7.2
        assert ExchangeRateManager._fallback('HKD', 'CNY') == 0.92

    def test_unknown_currency(self):
        assert ExchangeRateManager._fallback('XYZ', 'CNY') is None

    def test_non_cny_target(self):
        assert ExchangeRateManager._fallback('USD', 'EUR') is None

    def test_unsupported_pair_returns_1(self, manager):
        assert manager.get_rate('2024-06-15', 'XYZ', 'ABC') == 1.0


# --- Batch fetch ---

class TestBatchFetch:
    def test_saves_series_with_provider_source(self, db, manager, provider):
        provider.fetch_series.return_value = {
            '2024-01-02': 7.10, '2024-01-03': 7.12,
        }
        manager.batch_fetch(['2024-01-02', '2024-01-03'], 'USD', 'CNY')
        for d, expected in [('2024-01-02', 7.10), ('2024-01-03', 7.12)]:
            cached = db.get_exchange_rate(d, 'USD', 'CNY')
            assert cached['rate'] == expected
            assert cached['source'] == 'frankfurter'

    def test_skips_cached_dates(self, db, manager, provider):
        db.save_exchange_rate('2024-01-02', 'USD', 'CNY', 7.10, RateSource.FRANKFURTER)
        provider.fetch_series.return_value = {'2024-01-03': 7.12}
        manager.batch_fetch(['2024-01-02', '2024-01-03'], 'USD', 'CNY')
        assert db.get_exchange_rate('2024-01-02', 'USD', 'CNY')['rate'] == 7.10

    def test_falls_back_per_date_when_series_fails(self, db, manager):
        manager.batch_fetch(['2024-01-02'], 'USD', 'CNY')
        assert db.get_exchange_rate('2024-01-02', 'USD', 'CNY')['source'] == 'fallback'

    def test_non_trading_day_uses_previous_workday(self, db, manager, provider):
        """Weekend/holiday dates use the most recent prior workday rate."""
        provider.fetch_series.return_value = {
            '2025-04-25': 0.92,  # Friday
            '2025-04-28': 0.93,  # Monday
        }
        # 2025-04-26 is Saturday — should get Friday's rate
        manager.batch_fetch(['2025-04-25', '2025-04-26', '2025-04-28'], 'HKD', 'CNY')
        assert db.get_exchange_rate('2025-04-25', 'HKD', 'CNY')['rate'] == 0.92
        assert db.get_exchange_rate('2025-04-26', 'HKD', 'CNY')['rate'] == 0.92
        assert db.get_exchange_rate('2025-04-28', 'HKD', 'CNY')['rate'] == 0.93

    def test_empty_dates_is_noop(self, manager):
        manager.batch_fetch([], 'USD', 'CNY')


# --- DB source field ---

class TestDatabaseSourceField:
    def test_save_and_retrieve(self, db):
        db.save_exchange_rate('2024-01-01', 'USD', 'CNY', 7.2, 'frankfurter')
        result = db.get_exchange_rate('2024-01-01', 'USD', 'CNY')
        assert result == {'rate': 7.2, 'source': 'frankfurter'}

    def test_fallback_count(self, db):
        db.save_exchange_rate('2024-01-01', 'USD', 'CNY', 7.2, 'fallback')
        db.save_exchange_rate('2024-01-02', 'USD', 'CNY', 7.25, 'frankfurter')
        db.save_exchange_rate('2024-01-03', 'USD', 'CNY', 7.2, 'fallback')
        assert db.get_fallback_rate_count(2024) == 2
        assert db.get_fallback_rate_count(2025) == 0

    def test_default_source_is_unknown(self, db):
        db.save_exchange_rate('2024-01-01', 'USD', 'CNY', 7.2)
        assert db.get_exchange_rate('2024-01-01', 'USD', 'CNY')['source'] == 'unknown'
