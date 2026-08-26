"""Tests for market_data/providers/massive_provider.py."""

from datetime import datetime, timedelta

import pytest

from market_data.providers.massive_provider import MassiveProvider


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPStatusError
            raise HTTPStatusError("error", request=None, response=self)


class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        data = self.responses.get(endpoint)
        if isinstance(data, Exception):
            raise data
        return FakeResponse(data)

    async def aclose(self):
        pass


@pytest.fixture
def enabled_config():
    return {
        "market_data_apis": {
            "massive": {
                "enabled": True,
                "api_key": "test_key",
                "base_url": "https://api.massive.com",
            }
        }
    }


@pytest.mark.asyncio
async def test_get_ohlcv(enabled_config):
    provider = MassiveProvider(enabled_config)
    end = datetime.utcnow()
    start = end - timedelta(days=5)
    endpoint = (
        f"/v2/aggs/ticker/AAPL/range/1/hour/"
        f"{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
    )
    provider._client = FakeHTTPClient({
        endpoint: {
            "results": [
                {"t": 1724000000000, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1000},
                {"t": 1724003600000, "o": 100.5, "h": 102.0, "l": 100.0, "c": 101.5, "v": 1500},
            ]
        }
    })

    data = await provider.get_ohlcv("AAPL", multiplier=1, timespan="hour", days=5)
    assert data["symbol"] == "AAPL"
    assert data["timeframe"] == "1hour"
    assert data["source"] == "massive"
    assert len(data["candles"]) == 2
    assert data["candles"][-1]["close"] == 101.5


@pytest.mark.asyncio
async def test_get_snapshot(enabled_config):
    provider = MassiveProvider(enabled_config)
    provider._client = FakeHTTPClient({
        "/v2/snapshot/locale/us/markets/stocks/tickers/AAPL": {
            "ticker": {"day": {"c": 150.0, "v": 1000000}}
        }
    })

    snapshot = await provider.get_snapshot("AAPL")
    assert snapshot["ticker"]["day"]["c"] == 150.0


@pytest.mark.asyncio
async def test_disabled_provider_returns_none():
    config = {"market_data_apis": {"massive": {"enabled": False}}}
    provider = MassiveProvider(config)
    result = await provider.get_ohlcv("AAPL")
    assert result is None


@pytest.mark.asyncio
async def test_api_key_missing_disables_provider():
    config = {"market_data_apis": {"massive": {"enabled": True, "api_key": ""}}}
    provider = MassiveProvider(config)
    assert provider.enabled is False
    result = await provider.get_ohlcv("AAPL")
    assert result is None
