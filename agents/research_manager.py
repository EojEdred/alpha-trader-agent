"""
Research Manager Agent

Reads all analyst reports (technical, sentiment, news, fundamental) and produces
a unified investment plan with directional recommendation.

Inspired by TradingAgents' Research Manager.

Usage:
    from agents.research_manager import ResearchManager
    from strategies.registry import StrategyRegistry

    registry = StrategyRegistry()
    registry.discover()

    rm = ResearchManager()
    plan = await rm.synthesize("SPY", reports, price_data)
    print(plan.recommendation, plan.confidence)
"""

import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from loguru import logger

from models.decision_schemas import AnalystReport, ResearchPlan, Direction, Confidence
from tools.llm_factory import LLMFactory


class ResearchManager:
    """
    LLM-powered research manager that synthesizes multiple analyst reports
    into a single investment plan.
    """

    name = "research_manager"
    description = "Synthesizes analyst reports into an investment plan"

    def __init__(self, model_name: str = "kimi-k2"):
        self.model_name = model_name
        self._llm = None

    def _get_llm(self):
        """Lazy-load LLM. Uses Kimi CLI wrapper for reliability on text tasks."""
        if self._llm is None:
            from tools.llm_factory import KimiCLIWrapper
            self._llm = KimiCLIWrapper(temperature=0.1)
        return self._llm

    async def synthesize(
        self,
        symbol: str,
        reports: List[AnalystReport],
        price_data: Optional[Dict[str, Any]] = None,
    ) -> ResearchPlan:
        """
        Read all analyst reports and produce a unified research plan.

        Args:
            symbol: Ticker symbol
            reports: List of AnalystReport from all analysts
            price_data: Optional current price/quote data

        Returns:
            ResearchPlan with recommendation and rationale
        """
        if not reports:
            return ResearchPlan(
                symbol=symbol,
                recommendation=Direction.NEUTRAL,
                confidence=0.0,
                conviction_level=Confidence.LOW,
                analyst_agreement="No reports",
                rationale="No analyst reports available to synthesize",
                strategic_actions="Wait for analyst coverage",
                divergent_views=[],
                reports_considered=[],
            )

        # Build the prompt
        prompt = self._build_prompt(symbol, reports, price_data)

        try:
            # Call LLM
            llm = self._get_llm()
            from browser_use.llm.messages import UserMessage

            response = await llm.ainvoke([UserMessage(content=prompt)])
            content = self._extract_content(response)

            # Parse the response
            plan = self._parse_response(symbol, content, reports)
            logger.info(
                f"ResearchManager: {symbol} -> {plan.recommendation.value} "
                f"(confidence: {plan.confidence:.0%})"
            )
            return plan

        except Exception as e:
            logger.error(f"ResearchManager LLM failed for {symbol}: {e}")
            # Fallback: simple vote
            return self._fallback_plan(symbol, reports)

    @staticmethod
    def _extract_content(response) -> str:
        """Extract text content from various LLM response formats."""
        if hasattr(response, "completion") and response.completion:
            if isinstance(response.completion, str):
                return response.completion
        if hasattr(response, "content") and response.content:
            return response.content
        return str(response)

    def _build_prompt(
        self,
        symbol: str,
        reports: List[AnalystReport],
        price_data: Optional[Dict[str, Any]],
    ) -> str:
        """Build the prompt for the LLM."""
        lines = [
            f"You are the Research Manager for a trading desk. Analyze the following analyst reports for {symbol} and produce an investment plan.",
            "",
            "=== CURRENT MARKET DATA ===",
        ]

        if price_data:
            lines.append(f"Price: ${price_data.get('last', 'N/A')}")
            lines.append(f"Bid: ${price_data.get('bid', 'N/A')} / Ask: ${price_data.get('ask', 'N/A')}")
        else:
            lines.append("Current price data not available")

        lines.extend(["", "=== ANALYST REPORTS ===", ""])

        for i, report in enumerate(reports, 1):
            lines.append(f"--- Report {i}: {report.agent_name} ---")
            lines.append(f"Direction: {report.direction.value.upper()}")
            lines.append(f"Confidence: {report.confidence:.0%}")
            lines.append(f"Timeframe: {report.timeframe}")
            lines.append("Key Points:")
            for pt in report.key_points:
                lines.append(f"  - {pt}")
            lines.append("Risks:")
            for risk in report.risks:
                lines.append(f"  - {risk}")
            lines.append(f"Reasoning: {report.reasoning}")
            lines.append("")

        lines.extend([
            "=== YOUR TASK ===",
            "",
            "As Research Manager, you must:",
            "1. Evaluate the arguments from ALL analysts",
            "2. Identify which side (bullish/bearish) has stronger evidence",
            "3. Note any important disagreements or risks",
            "4. Produce a clear investment recommendation",
            "",
            "Respond in this exact format:",
            "",
            "RECOMMENDATION: [Buy | Overweight | Hold | Underweight | Sell]",
            "CONFIDENCE: [0.0 - 1.0]",
            "RATIONALE: [2-3 sentences summarizing the debate and your conclusion]",
            "STRATEGIC_ACTIONS: [Specific steps: entry price, stop loss, target, position size guidance]",
            "DIVERGENT_VIEWS: [What the losing side argued - 1-2 sentences]",
            "",
        ])

        return "\n".join(lines)

    def _parse_response(self, symbol: str, content: str, reports: List[AnalystReport]) -> ResearchPlan:
        """Parse LLM response into a ResearchPlan."""
        import re

        # Extract fields with regex
        rec_match = re.search(r"RECOMMENDATION:\s*(.+?)(?:\n|$)", content, re.IGNORECASE)
        conf_match = re.search(r"CONFIDENCE:\s*(0\.\d+|1\.0|1|0)", content, re.IGNORECASE)
        rat_match = re.search(r"RATIONALE:\s*(.+?)(?:\n\n|\n[A-Z]|$)", content, re.IGNORECASE | re.DOTALL)
        act_match = re.search(r"STRATEGIC_ACTIONS:\s*(.+?)(?:\n\n|\n[A-Z]|$)", content, re.IGNORECASE | re.DOTALL)
        div_match = re.search(r"DIVERGENT_VIEWS:\s*(.+?)(?:\n\n|\n[A-Z]|$)", content, re.IGNORECASE | re.DOTALL)

        recommendation_str = (rec_match.group(1).strip() if rec_match else "Hold").lower()
        confidence = float(conf_match.group(1)) if conf_match else 0.5

        # Map recommendation string to Direction
        if "buy" in recommendation_str or "overweight" in recommendation_str:
            recommendation = Direction.LONG
        elif "sell" in recommendation_str or "underweight" in recommendation_str:
            recommendation = Direction.SHORT
        else:
            recommendation = Direction.NEUTRAL

        # Determine conviction level
        if confidence > 0.8:
            conviction = Confidence.HIGH
        elif confidence > 0.5:
            conviction = Confidence.MEDIUM
        else:
            conviction = Confidence.LOW

        # Count analyst agreement
        long_count = sum(1 for r in reports if r.direction == Direction.LONG)
        short_count = sum(1 for r in reports if r.direction == Direction.SHORT)
        neutral_count = sum(1 for r in reports if r.direction == Direction.NEUTRAL)
        agreement = f"{long_count} bullish, {short_count} bearish, {neutral_count} neutral"

        return ResearchPlan(
            symbol=symbol,
            recommendation=recommendation,
            confidence=confidence,
            conviction_level=conviction,
            analyst_agreement=agreement,
            rationale=rat_match.group(1).strip() if rat_match else "No rationale provided",
            strategic_actions=act_match.group(1).strip() if act_match else "No specific actions",
            divergent_views=[div_match.group(1).strip()] if div_match else [],
            reports_considered=[r.agent_name for r in reports],
        )

    def _fallback_plan(self, symbol: str, reports: List[AnalystReport]) -> ResearchPlan:
        """Simple voting fallback when LLM fails."""
        long_count = sum(1 for r in reports if r.direction == Direction.LONG)
        short_count = sum(1 for r in reports if r.direction == Direction.SHORT)
        total = len(reports)

        if long_count > short_count and long_count / total > 0.5:
            rec = Direction.LONG
            conf = long_count / total
        elif short_count > long_count and short_count / total > 0.5:
            rec = Direction.SHORT
            conf = short_count / total
        else:
            rec = Direction.NEUTRAL
            conf = 0.5

        return ResearchPlan(
            symbol=symbol,
            recommendation=rec,
            confidence=conf,
            conviction_level=Confidence.MEDIUM if conf > 0.5 else Confidence.LOW,
            analyst_agreement=f"{long_count} bullish, {short_count} bearish out of {total}",
            rationale="Fallback vote due to LLM failure",
            strategic_actions="Review manually before trading",
            divergent_views=[],
            reports_considered=[r.agent_name for r in reports],
        )
