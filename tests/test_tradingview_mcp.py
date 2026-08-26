"""Tests for tools/tradingview_mcp.py."""

import pytest

from models.decision_schemas import AnalystReport, Confidence, Direction
from tools.tradingview_mcp import TradingViewMCP


class FakeMCPClient:
    """Fake MCP client that returns canned responses."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def list_tools(self, server_name):
        return [{"name": n} for n in self.responses.get("_tools", [])]

    async def call_tool(self, server_name, tool_name, arguments, timeout_seconds=None):
        self.calls.append((server_name, tool_name, arguments, timeout_seconds))
        data = self.responses.get(tool_name)
        if isinstance(data, Exception):
            raise data

        class Result:
            def __init__(self, text):
                self.text = text
                self.data = text if isinstance(text, dict) else None
                self.is_error = False
                self.content = []

        return Result(data)


@pytest.fixture
def bullish_client():
    return FakeMCPClient(
        {
            "coin_analysis": {
                "recommendation": "buy",
                "confidence": 0.85,
                "timeframe": "1d",
                "summary": "Bullish engulfing with volume expansion.",
                "indicators": {"RSI": 58, "MACD": "bullish crossover"},
                "risks": ["Resistance at prior highs"],
            },
            "bollinger_scan": {
                "results": [
                    {"symbol": "AAPL", "score": 0.82, "summary": "Upper band breakout"},
                    {"symbol": "TSLA", "score": 0.71, "summary": "Squeeze breakout"},
                ]
            },
        }
    )


@pytest.mark.asyncio
async def test_analyze_symbol_bullish(bullish_client):
    tv = TradingViewMCP(client=bullish_client)
    report = await tv.analyze_symbol("AAPL", exchange="NASDAQ", timeframe="1d")

    assert isinstance(report, AnalystReport)
    assert report.symbol == "AAPL"
    assert report.direction == Direction.LONG
    assert report.confidence == 0.85
    assert report.conviction_level == Confidence.HIGH
    assert "Bullish engulfing" in report.reasoning
    assert report.agent_name == "tradingview_ta"


@pytest.mark.asyncio
async def test_analyze_symbol_degrades_gracefully():
    client = FakeMCPClient({"coin_analysis": None})
    tv = TradingViewMCP(client=client)
    report = await tv.analyze_symbol("AAPL")

    assert report.direction == Direction.NEUTRAL
    assert report.confidence == 0.0
    assert report.conviction_level == Confidence.LOW


@pytest.mark.asyncio
async def test_scan_market(bullish_client):
    tv = TradingViewMCP(client=bullish_client)
    evidence = await tv.scan_market("bollinger_breakout")

    assert len(evidence) == 2
    assert evidence[0].title == "bollinger_breakout: AAPL"
    assert evidence[0].confidence == 0.82
    assert "tradingview" in evidence[0].tags


@pytest.mark.asyncio
async def test_scan_market_degrades_gracefully():
    client = FakeMCPClient({"bollinger_scan": None})
    tv = TradingViewMCP(client=client)
    evidence = await tv.scan_market("bollinger_breakout")
    assert evidence == []


@pytest.mark.asyncio
async def test_run_backtest():
    client = FakeMCPClient(
        {
            "backtest_strategy": {
                "total_return": 12.5,
                "sharpe": 1.1,
                "trades": 20,
            }
        }
    )
    tv = TradingViewMCP(client=client)
    result = await tv.run_backtest("AAPL", strategy="rsi")

    assert result["total_return"] == 12.5
    assert result["sharpe"] == 1.1


@pytest.mark.asyncio
async def test_multi_timeframe_calls_correct_tool():
    client = FakeMCPClient(
        {
            "multi_timeframe_analysis": {
                "recommendation": "sell",
                "confidence": 0.65,
                "timeframe": "1h,4h,1d",
            }
        }
    )
    tv = TradingViewMCP(client=client)
    report = await tv.analyze_multi_timeframe("SPY")

    assert report.direction == Direction.SHORT
    assert report.confidence == 0.65
    assert any(
        call[1] == "multi_timeframe_analysis" for call in client.calls
    )
