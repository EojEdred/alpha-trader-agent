"""Tests for tools/auto_research.py."""

import pytest

from models import EvidenceItem
from models.decision_schemas import AnalystReport, Confidence, Direction, ResearchPlan
from tools.auto_research import AutoResearchEngine


class FakeMemoryLog:
    def __init__(self):
        self.reports = []
        self.plans = []

    def record_analyst_report(self, report):
        self.reports.append(report)

    def record_research_plan(self, plan):
        self.plans.append(plan)


class FakeTradingViewMCP:
    async def analyze_symbol(self, symbol, exchange="NASDAQ", timeframe="1d"):
        return AnalystReport(
            agent_name="tradingview_ta",
            symbol=symbol,
            direction=Direction.LONG,
            confidence=0.75,
            conviction_level=Confidence.MEDIUM,
            key_points=["Bullish trend"],
            risks=["Resistance"],
            timeframe="1d",
            evidence={},
            reasoning=f"{symbol} looks bullish",
        )

    async def analyze_multi_timeframe(self, symbol, exchange="NASDAQ"):
        return AnalystReport(
            agent_name="tradingview_mtf",
            symbol=symbol,
            direction=Direction.LONG,
            confidence=0.7,
            conviction_level=Confidence.MEDIUM,
            key_points=["Higher timeframes align"],
            risks=["Short-term pullback"],
            timeframe="1h,4h,1d",
            evidence={},
            reasoning=f"{symbol} multi-timeframe bullish",
        )

    async def multi_agent_debate(self, symbol, exchange="NASDAQ", timeframe="1d"):
        return AnalystReport(
            agent_name="tradingview_debate",
            symbol=symbol,
            direction=Direction.NEUTRAL,
            confidence=0.55,
            conviction_level=Confidence.LOW,
            key_points=["Mixed signals"],
            risks=["Uncertainty"],
            timeframe="1d",
            evidence={},
            reasoning=f"{symbol} debate neutral",
        )

    async def scan_market(self, scan_type, market="america", limit=20):
        return []


class FakeUnusualWhalesClient:
    async def flow_evidence(self, symbol=None, limit=50):
        return [
            EvidenceItem(
                id="evd_1",
                url=f"https://unusualwhales.com/flow/{symbol}",
                title=f"UW Flow: {symbol}",
                snippet="Large call sweep",
                timestamp=__import__("datetime").datetime.utcnow(),
                confidence=0.8,
                tags=["unusual_whales", "options_flow", symbol],
            )
        ]

    async def gex_analyst_report(self, symbol):
        return AnalystReport(
            agent_name="unusual_whales_gex",
            symbol=symbol,
            direction=Direction.NEUTRAL,
            confidence=0.6,
            conviction_level=Confidence.MEDIUM,
            key_points=["Net GEX positive"],
            risks=["Pin risk"],
            timeframe="1d",
            evidence={},
            reasoning=f"{symbol} GEX pin risk",
        )

    async def dark_pool_evidence(self, symbol=None, limit=50):
        return []


@pytest.fixture
def engine(tmp_path):
    config = {
        "auto_research": {
            "max_symbols_per_cycle": 10,
            "confidence_threshold": 0.5,
            "save_evidence": True,
            "output_dir": str(tmp_path),
        }
    }
    memory = FakeMemoryLog()
    return AutoResearchEngine(
        config=config,
        tv_mcp=FakeTradingViewMCP(),
        uw_client=FakeUnusualWhalesClient(),
        memory_log=memory,
    )


@pytest.mark.asyncio
async def test_run_cycle(engine):
    result = await engine.run_cycle(symbols=["AAPL", "SPY"])

    assert result["symbols"] == ["AAPL", "SPY"]
    assert result["evidence_count"] > 0
    assert len(result["plans"]) > 0
    assert result["thesis"] is not None
    assert result["report_path"]
    assert "Regime:" in result["summary"]


@pytest.mark.asyncio
async def test_research_symbol(engine):
    evidence, reports = await engine.research_symbol("AAPL")
    assert len(evidence) > 0
    assert len(reports) > 0
    assert any(r.agent_name == "tradingview_ta" for r in reports)
    assert any("unusual_whales" in e.tags for e in evidence)


@pytest.mark.asyncio
async def test_resolve_symbols_from_watchlists(tmp_path):
    config = {
        "watchlists": {
            "options": ["SPY", "QQQ"],
            "futures": ["ES"],
        },
        "auto_research": {"output_dir": str(tmp_path)},
    }
    engine = AutoResearchEngine(
        config=config,
        tv_mcp=FakeTradingViewMCP(),
        uw_client=FakeUnusualWhalesClient(),
        memory_log=FakeMemoryLog(),
    )
    symbols = engine._resolve_symbols(None)
    assert symbols == ["SPY", "QQQ", "ES"]


def test_build_summary(engine):
    plans = [
        ResearchPlan(
            symbol="AAPL",
            recommendation=Direction.LONG,
            confidence=0.8,
            conviction_level=Confidence.HIGH,
            analyst_agreement="2/2 bullish",
            rationale="Bullish",
            strategic_actions="Buy",
            divergent_views=[],
            reports_considered=["tv"],
        ),
        ResearchPlan(
            symbol="SPY",
            recommendation=Direction.SHORT,
            confidence=0.7,
            conviction_level=Confidence.MEDIUM,
            analyst_agreement="1/2 bearish",
            rationale="Bearish",
            strategic_actions="Sell",
            divergent_views=[],
            reports_considered=["tv"],
        ),
    ]
    from models import ThesisObject, generate_thesis_id
    from datetime import datetime

    thesis = ThesisObject(
        id=generate_thesis_id(),
        summary="Mixed",
        evidence_ids=[],
        conviction=0.6,
        regime_bias="neutral",
        created_at=datetime.utcnow(),
    )
    summary = engine._build_summary(plans, thesis)
    assert "1 long" in summary
    assert "1 short" in summary
