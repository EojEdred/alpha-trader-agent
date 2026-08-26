"""Tests for agents/valuecell_analyst.py."""

import pytest
from unittest.mock import AsyncMock, patch

from agents.valuecell_analyst import ValueCellAnalyst
from models.decision_schemas import Direction


@pytest.fixture
def analyst():
    return ValueCellAnalyst({})


@pytest.mark.asyncio
async def test_disabled_returns_neutral(analyst):
    # No provider configured -> neutral report
    report = await analyst.analyze("AAPL")
    assert report.agent_name == "valuecell_analyst"
    assert report.symbol == "AAPL"
    assert report.direction == Direction.NEUTRAL


@pytest.mark.asyncio
async def test_news_sentiment_bullish(analyst):
    news = {
        "results": [
            {"title": "AAPL beats earnings", "description": "Strong growth and upgrade"},
            {"title": "iPhone demand strong", "description": "Bullish outlook"},
        ]
    }

    with patch.object(analyst.provider, "get_news", new=AsyncMock(return_value=news)):
        # Mock LLM deep research
        fake_llm_response = type("R", (), {"content": "SUMMARY: AAPL looks strong\nKEY_POINTS:\n- Growth\nRISKS:\n- Valuation\nSENTIMENT: bullish"})()
        with patch.object(analyst, "_get_llm", return_value=type("LLM", (), {"ainvoke": AsyncMock(return_value=fake_llm_response)})()):
            report = await analyst.analyze("AAPL")

    assert report.direction == Direction.LONG
    assert report.confidence > 0.5


@pytest.mark.asyncio
async def test_evidence_for_symbol(analyst):
    news = {
        "results": [
            {"title": "AAPL news", "description": "desc", "article_url": "https://example.com"},
        ]
    }

    with patch.object(analyst.provider, "get_news", new=AsyncMock(return_value=news)):
        analyst.provider.enabled = True
        evidence = await analyst.evidence_for_symbol("AAPL")

    assert len(evidence) == 1
    assert "valuecell" in evidence[0].tags
