"""Tests for analyst agents and ResearchManager upgrade."""

import pytest

from agents.technical_analyst import TechnicalAnalyst
from agents.flow_analyst import FlowAnalyst
from agents.sentiment_analyst import SentimentAnalyst
from agents.quant_analyst import QuantAnalyst
from agents.research_manager import ResearchManager
from models import EvidenceItem
from models.decision_schemas import AnalystReport, Confidence, Direction, ResearchPlan


class FakeTV:
    async def analyze_symbol(self, symbol, exchange="NASDAQ", timeframe="1d"):
        return AnalystReport(
            agent_name="tradingview_ta",
            symbol=symbol,
            direction=Direction.LONG,
            confidence=0.75,
            conviction_level=Confidence.MEDIUM,
            key_points=["Bullish"],
            risks=["Resistance"],
            timeframe="1d",
            evidence={},
            reasoning="Bullish",
        )

    async def analyze_multi_timeframe(self, symbol, exchange="NASDAQ"):
        return AnalystReport(
            agent_name="tradingview_mtf",
            symbol=symbol,
            direction=Direction.LONG,
            confidence=0.8,
            conviction_level=Confidence.HIGH,
            key_points=["Aligned"],
            risks=["Pullback"],
            timeframe="1h,4h,1d",
            evidence={},
            reasoning="Aligned",
        )

    async def combined_ta_news_sentiment(self, symbol, exchange="NASDAQ", timeframe="1d"):
        return AnalystReport(
            agent_name="tradingview_combined",
            symbol=symbol,
            direction=Direction.SHORT,
            confidence=0.6,
            conviction_level=Confidence.MEDIUM,
            key_points=["Negative news"],
            risks=["Bounce"],
            timeframe="1d",
            evidence={},
            reasoning="Negative news",
        )

    async def bitcoin_market_pulse(self):
        return EvidenceItem(
            id="evd_1",
            url="mcp://tradingview/btc_pulse",
            title="BTC Pulse",
            snippet="Bullish macro",
            timestamp=__import__("datetime").datetime.utcnow(),
            confidence=0.7,
            tags=["macro"],
        )


class FakeUW:
    async def flow_evidence(self, symbol=None, limit=50):
        return [
            EvidenceItem(
                id="evd_1",
                url="",
                title="Flow",
                snippet="CALL sweep",
                timestamp=__import__("datetime").datetime.utcnow(),
                confidence=0.8,
                tags=["unusual_whales", "options_flow", symbol],
            )
        ]

    async def dark_pool_evidence(self, symbol=None, limit=50):
        return []

    async def gex_analyst_report(self, symbol):
        return AnalystReport(
            agent_name="unusual_whales_gex",
            symbol=symbol,
            direction=Direction.NEUTRAL,
            confidence=0.6,
            conviction_level=Confidence.MEDIUM,
            key_points=["Net GEX positive"],
            risks=["Pin"],
            timeframe="1d",
            evidence={},
            reasoning="Pin risk",
        )


@pytest.mark.asyncio
async def test_technical_analyst_uses_mtf():
    agent = TechnicalAnalyst(config={})
    agent.tv = FakeTV()
    report = await agent.analyze("AAPL")
    assert report.agent_name == "technical_analyst"
    assert report.direction == Direction.LONG
    assert report.confidence == 0.8


@pytest.mark.asyncio
async def test_flow_analyst():
    agent = FlowAnalyst(config={})
    agent.uw = FakeUW()
    report = await agent.analyze("AAPL")
    assert report.agent_name == "flow_analyst"
    assert report.direction == Direction.LONG
    assert report.confidence > 0.0


@pytest.mark.asyncio
async def test_sentiment_analyst():
    agent = SentimentAnalyst(config={})
    agent.tv = FakeTV()
    report = await agent.analyze("AAPL")
    assert report.agent_name == "sentiment_analyst"
    assert report.direction == Direction.SHORT


@pytest.mark.asyncio
async def test_quant_analyst_uses_vibe_trading():
    agent = QuantAnalyst(config={})
    report = await agent.analyze("AAPL")
    # When Vibe-Trading is not configured, it degrades to a neutral placeholder
    assert report.direction == Direction.NEUTRAL


def test_research_manager_weighted_fallback():
    rm = ResearchManager(
        config={
            "analyst_weights": {
                "technical_analyst": 2.0,
                "flow_analyst": 0.5,
            }
        }
    )
    reports = [
        AnalystReport(
            agent_name="technical_analyst",
            symbol="SPY",
            direction=Direction.LONG,
            confidence=0.9,
            conviction_level=Confidence.HIGH,
            key_points=["Bullish"],
            risks=["None"],
            timeframe="1d",
            evidence={},
            reasoning="Bullish",
        ),
        AnalystReport(
            agent_name="flow_analyst",
            symbol="SPY",
            direction=Direction.SHORT,
            confidence=0.9,
            conviction_level=Confidence.HIGH,
            key_points=["Bearish flow"],
            risks=["None"],
            timeframe="1d",
            evidence={},
            reasoning="Bearish",
        ),
    ]
    plan = rm._fallback_plan("SPY", reports)
    assert plan.recommendation == Direction.LONG
    assert plan.confidence > 0.5


def test_research_manager_weight_in_prompt():
    rm = ResearchManager(config={"analyst_weights": {"technical_analyst": 2.0}})
    reports = [
        AnalystReport(
            agent_name="technical_analyst",
            symbol="SPY",
            direction=Direction.LONG,
            confidence=0.8,
            conviction_level=Confidence.HIGH,
            key_points=["Bullish"],
            risks=["None"],
            timeframe="1d",
            evidence={},
            reasoning="Bullish",
        )
    ]
    prompt = rm._build_prompt("SPY", reports, None)
    assert "weight: 2.00" in prompt
