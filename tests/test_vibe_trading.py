"""Tests for tools/vibe_trading.py."""

import pytest

from models.decision_schemas import Direction
from tools.vibe_trading import VibeTradingSidecar


class FakeMCPClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

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
def factor_client():
    return FakeMCPClient({
        "factor_analysis": {
            "signal": "buy",
            "confidence": 0.82,
            "summary": "Momentum and mean reversion factors are bullish.",
            "factors": {"momentum": 0.7, "mean_reversion": 0.6, "volatility": -0.2},
        }
    })


@pytest.mark.asyncio
async def test_factor_analyst_report(factor_client):
    vibe = VibeTradingSidecar(client=factor_client)
    report = await vibe.factor_analyst_report("AAPL")
    assert report.agent_name == "vibe_trading_factor"
    assert report.direction == Direction.LONG
    assert report.confidence == 0.82
    assert "Momentum" in report.reasoning


@pytest.mark.asyncio
async def test_factor_analyst_report_degrades_gracefully():
    client = FakeMCPClient({"factor_analysis": None})
    vibe = VibeTradingSidecar(client=client)
    report = await vibe.factor_analyst_report("AAPL")
    assert report.direction == Direction.NEUTRAL
    assert report.confidence == 0.0


@pytest.mark.asyncio
async def test_alpha_zoo_evidence():
    client = FakeMCPClient({
        "alpha_zoo": {
            "alphas": [
                {"name": "alpha_1", "ic": 0.05},
                {"name": "alpha_2", "ic": 0.12},
            ]
        }
    })
    vibe = VibeTradingSidecar(client=client)
    evidence = await vibe.alpha_zoo_evidence("AAPL")
    assert len(evidence) == 2
    assert evidence[1].confidence == 0.12
    assert "vibe_trading" in evidence[0].tags


@pytest.mark.asyncio
async def test_shadow_backtest():
    client = FakeMCPClient({
        "run_shadow_backtest": {
            "delta_pnl": 0.05,
            "rules": ["buy on RSI < 30"],
        }
    })
    vibe = VibeTradingSidecar(client=client)
    result = await vibe.shadow_backtest("data/journal.csv")
    assert result["delta_pnl"] == 0.05
    assert any(call[1] == "run_shadow_backtest" for call in client.calls)
