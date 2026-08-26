"""
Technical Analyst Agent

Uses TradingView MCP technical analysis tools to produce an AnalystReport.
Weights multiple timeframes and can combine TA with news/sentiment.
"""

from typing import Any, Dict, Optional

from models.decision_schemas import AnalystReport
from agents.base_analyst import BaseAnalyst
from tools.tradingview_mcp import TradingViewMCP


class TechnicalAnalyst(BaseAnalyst):
    """Technical analyst powered by TradingView MCP."""

    name = "technical_analyst"
    description = "Technical analysis via TradingView indicators and multi-timeframe alignment"
    default_weight = 1.0

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.tv = TradingViewMCP(self.config)

    async def analyze(
        self,
        symbol: str,
        price_data: Optional[Dict[str, Any]] = None,
    ) -> AnalystReport:
        """
        Run TradingView analysis across timeframes and return a consensus report.

        If the MCP server is unavailable, returns a low-confidence neutral report
        so the ResearchManager can fall back to other analysts.
        """
        # Prefer multi-timeframe when available; it already aggregates multiple TAs.
        mtf_report = await self.tv.analyze_multi_timeframe(symbol)
        if mtf_report.confidence > 0:
            mtf_report.agent_name = self.name
            return mtf_report

        # Fallback to single-timeframe analysis
        single_report = await self.tv.analyze_symbol(symbol)
        single_report.agent_name = self.name
        return single_report
