"""Tests for agents/massive_analyst.py."""

import pytest
from unittest.mock import AsyncMock, patch

from agents.massive_analyst import MassiveAnalyst
from models.decision_schemas import AnalystReport, Direction


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


@pytest.fixture
def analyst(enabled_config):
    return MassiveAnalyst(enabled_config)


@pytest.mark.asyncio
async def test_bullish_bias(analyst):
    ohlcv = {
        "candles": [
            {"timestamp": "2026-08-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"timestamp": "2026-08-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"timestamp": "2026-08-03", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1000},
            {"timestamp": "2026-08-04", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1000},
            {"timestamp": "2026-08-05", "open": 103, "high": 106, "low": 103, "close": 105, "volume": 5000},
            {"timestamp": "2026-08-06", "open": 105, "high": 107, "low": 104, "close": 106, "volume": 5000},
        ]
    }
    snapshot = {"ticker": "AAPL", "day": {"c": 106.5}}

    with patch.object(analyst.provider, "get_ohlcv", new=AsyncMock(return_value=ohlcv)):
        with patch.object(analyst.provider, "get_snapshot", new=AsyncMock(return_value=snapshot)):
            report = await analyst.analyze("AAPL")

    assert isinstance(report, AnalystReport)
    assert report.agent_name == "massive_analyst"
    assert report.symbol == "AAPL"
    assert report.direction == Direction.LONG
    assert report.confidence > 0.5


@pytest.mark.asyncio
async def test_bearish_bias(analyst):
    ohlcv = {
        "candles": [
            {"timestamp": "2026-08-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"timestamp": "2026-08-02", "open": 100, "high": 101, "low": 98, "close": 99, "volume": 1000},
            {"timestamp": "2026-08-03", "open": 99, "high": 100, "low": 97, "close": 98, "volume": 1000},
            {"timestamp": "2026-08-04", "open": 98, "high": 99, "low": 96, "close": 97, "volume": 1000},
            {"timestamp": "2026-08-05", "open": 97, "high": 98, "low": 95, "close": 96, "volume": 5000},
            {"timestamp": "2026-08-06", "open": 96, "high": 97, "low": 94, "close": 95, "volume": 5000},
        ]
    }
    snapshot = {"ticker": "AAPL", "day": {"c": 94.5}}

    with patch.object(analyst.provider, "get_ohlcv", new=AsyncMock(return_value=ohlcv)):
        with patch.object(analyst.provider, "get_snapshot", new=AsyncMock(return_value=snapshot)):
            report = await analyst.analyze("AAPL")

    assert report.direction == Direction.SHORT
    assert report.confidence > 0.5


@pytest.mark.asyncio
async def test_disabled_returns_neutral(analyst):
    with patch.object(analyst.provider, "get_ohlcv", new=AsyncMock(return_value=None)):
        with patch.object(analyst.provider, "get_snapshot", new=AsyncMock(return_value=None)):
            report = await analyst.analyze("AAPL")

    assert report.direction == Direction.NEUTRAL
    assert report.confidence == 0.0


@pytest.mark.asyncio
async def test_evidence_for_symbol(analyst):
    snapshot = {"ticker": "AAPL", "day": {"c": 150.0}}
    news = {
        "results": [
            {"title": "AAPL beats earnings", "description": "Strong iPhone sales", "article_url": "https://example.com/a"},
        ]
    }

    with patch.object(analyst.provider, "get_snapshot", new=AsyncMock(return_value=snapshot)):
        with patch.object(analyst.provider, "get_news", new=AsyncMock(return_value=news)):
            evidence = await analyst.evidence_for_symbol("AAPL")

    assert len(evidence) == 2  # snapshot + one news article
    tags = {tag for e in evidence for tag in e.tags}
    assert "massive" in tags
    assert "news" in tags
