"""
Quant Analyst Agent

Placeholder for quant/factor analysis. Currently returns a neutral report
and is designed to integrate with Vibe-Trading's Alpha Zoo / factor analysis
in a future upgrade.

When vibe-trading-mcp is enabled, this agent will call factor_analysis and
alpha_zoo tools to score symbols on quantitative factors.
"""

from typing import Any, Dict, Optional

from models.decision_schemas import AnalystReport
from agents.base_analyst import BaseAnalyst
from tools.vibe_trading import VibeTradingSidecar


class QuantAnalyst(BaseAnalyst):
    """Quantitative factor analyst powered by Vibe-Trading."""

    name = "quant_analyst"
    description = "Quantitative factor and alpha analysis via Vibe-Trading"
    default_weight = 0.8

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.vibe = VibeTradingSidecar(self.config)

    async def analyze(
        self,
        symbol: str,
        price_data: Optional[Dict[str, Any]] = None,
    ) -> AnalystReport:
        """
        Analyze a symbol using Vibe-Trading factor analysis.

        If Vibe-Trading MCP is not enabled, returns a low-confidence placeholder
        report so the ResearchManager can ignore it gracefully.
        """
        return await self.vibe.factor_analyst_report(symbol)
