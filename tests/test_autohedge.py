"""Tests for AutoHedge adapter and director integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.autohedge_director import AutoHedgeDirector
from tools.autohedge_adapter import AutoHedgeAdapter


@pytest.mark.asyncio
async def test_autohedge_adapter_parses_recommendations():
    adapter = AutoHedgeAdapter({})
    messages = [
        {"role": "director", "content": "AAPL looks bullish. Buy at $150 with stop $145 and target $160."},
        {"role": "quant", "content": "Technical score 0.8. Confidence high."},
    ]
    recs = adapter._extract_recommendations(messages)
    assert len(recs) >= 1
    aapl = next((r for r in recs if r["symbol"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["direction"] == "long"
    assert aapl["entry_price"] == 150.0


@pytest.mark.asyncio
async def test_autohedge_adapter_degrades_when_unavailable():
    with patch("tools.autohedge_adapter._AUTOHEDGE_AVAILABLE", False):
        adapter = AutoHedgeAdapter({})
        result = await adapter.run("Analyze AAPL")

    assert result["status"] == "degraded"
    assert result["recommendations"] == []


@pytest.mark.asyncio
async def test_autohedge_director_runs_cycle():
    config = {"analyst_weights": {}}
    director = AutoHedgeDirector(config)

    # Mock analysts so no external calls are needed
    fake_report = MagicMock()
    fake_report.agent_name = "massive_analyst"
    fake_report.symbol = "AAPL"
    fake_report.direction = MagicMock()
    fake_report.direction.value = "long"
    fake_report.confidence = 0.7
    fake_report.key_points = []
    fake_report.risks = []
    fake_report.timeframe = "swing"
    fake_report.evidence = {"current_price": 150.0}
    fake_report.reasoning = "bullish"
    fake_report.model_dump.return_value = {
        "agent_name": "massive_analyst",
        "symbol": "AAPL",
        "direction": "long",
        "confidence": 0.7,
    }
    fake_report.conviction_level = MagicMock()
    fake_report.conviction_level.value = "medium"

    with patch("agents.autohedge_director.MassiveAnalyst") as mock_cls:
        instance = mock_cls.return_value
        instance.analyze = AsyncMock(return_value=fake_report)
        instance.default_weight = 0.9
        result = await director.run_cycle("AAPL")

    assert result["primary_symbol"] == "AAPL"
    assert len(result["recommendations"]) == 1
    assert result["recommendations"][0]["symbol"] == "AAPL"
