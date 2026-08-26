"""Tests for tools/unusual_whales.py."""

import pytest

from models.decision_schemas import Direction
from tools.unusual_whales import UnusualWhalesClient


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPStatusError
            raise HTTPStatusError(
                "error", request=None, response=self
            )


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
            "options_flow": {
                "enabled": True,
                "api_key": "test_key",
                "base_url": "https://api.unusualwhales.com",
            }
        }
    }


@pytest.mark.asyncio
async def test_flow_evidence(enabled_config):
    client = UnusualWhalesClient(enabled_config)
    client._client = FakeHTTPClient({
        "/api/flow": {
            "data": [
                {
                    "symbol": "AAPL",
                    "side": "CALL",
                    "strike": 180,
                    "expiry": "2026-08-21",
                    "premium": 250000,
                    "size": 1500,
                    "sentiment": "bullish",
                    "sweep": True,
                }
            ]
        }
    })

    evidence = await client.flow_evidence(symbol="AAPL", limit=10)
    assert len(evidence) == 1
    assert evidence[0].tags == ["unusual_whales", "options_flow", "AAPL", "sweep"]
    assert evidence[0].confidence > 0.8
    assert "CALL AAPL 180" in evidence[0].snippet


@pytest.mark.asyncio
async def test_gex_analyst_report(enabled_config):
    client = UnusualWhalesClient(enabled_config)
    client._client = FakeHTTPClient({
        "/api/gex": {
            "net_gex": 1_500_000_000,
            "price": 450.0,
            "key_levels": [445, 450, 455],
        }
    })

    report = await client.gex_analyst_report("SPY")
    assert report.symbol == "SPY"
    assert report.agent_name == "unusual_whales_gex"
    assert report.direction == Direction.NEUTRAL
    assert report.confidence > 0.0


@pytest.mark.asyncio
async def test_gex_analyst_report_degrades_gracefully(enabled_config):
    client = UnusualWhalesClient(enabled_config)
    client._client = FakeHTTPClient({"/api/gex": None})

    report = await client.gex_analyst_report("SPY")
    assert report.direction == Direction.NEUTRAL
    assert report.confidence == 0.0


@pytest.mark.asyncio
async def test_disabled_client_returns_empty():
    config = {"market_data_apis": {"options_flow": {"enabled": False}}}
    client = UnusualWhalesClient(config)
    evidence = await client.flow_evidence("AAPL")
    assert evidence == []


@pytest.mark.asyncio
async def test_dark_pool_evidence(enabled_config):
    client = UnusualWhalesClient(enabled_config)
    client._client = FakeHTTPClient({
        "/api/dark-pool": {
            "prints": [
                {"symbol": "SPY", "price": 450.0, "size": 100000},
            ]
        }
    })

    evidence = await client.dark_pool_evidence(symbol="SPY")
    assert len(evidence) == 1
    assert "Dark pool print" in evidence[0].snippet
    assert "unusual_whales" in evidence[0].tags


@pytest.mark.asyncio
async def test_market_tide_evidence(enabled_config):
    client = UnusualWhalesClient(enabled_config)
    client._client = FakeHTTPClient({
        "/api/market-tide": {"net_premium": 1_200_000_000}
    })

    evidence = await client.market_tide_evidence()
    assert evidence is not None
    assert "Market Tide" in evidence.title
    assert "bullish" in evidence.snippet
