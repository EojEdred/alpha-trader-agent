"""
Flow Analyst Agent

Uses Unusual Whales options flow, GEX, and dark pool data to produce
an AnalystReport. Focuses on positioning and unusual institutional activity.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from models import EvidenceItem
from models.decision_schemas import AnalystReport, Confidence, Direction
from agents.base_analyst import BaseAnalyst
from tools.unusual_whales import UnusualWhalesClient


class FlowAnalyst(BaseAnalyst):
    """Options flow and alternative-data analyst powered by Unusual Whales."""

    name = "flow_analyst"
    description = "Options flow, GEX, and dark pool analysis via Unusual Whales"
    default_weight = 0.9

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.uw = UnusualWhalesClient(self.config)

    async def analyze(
        self,
        symbol: str,
        price_data: Optional[Dict[str, Any]] = None,
    ) -> AnalystReport:
        """
        Analyze options flow, GEX, and dark pool prints for a symbol.

        Returns a consensus AnalystReport combining flow direction and GEX context.
        """
        evidence: List[EvidenceItem] = []

        try:
            evidence.extend(await self.uw.flow_evidence(symbol=symbol, limit=20))
        except Exception as e:
            logger.warning(f"FlowAnalyst flow failed for {symbol}: {e}")

        try:
            evidence.extend(await self.uw.dark_pool_evidence(symbol=symbol, limit=10))
        except Exception as e:
            logger.warning(f"FlowAnalyst dark pool failed for {symbol}: {e}")

        try:
            gex_report = await self.uw.gex_analyst_report(symbol)
        except Exception as e:
            logger.warning(f"FlowAnalyst GEX failed for {symbol}: {e}")
            gex_report = AnalystReport(
                agent_name=self.name,
                symbol=symbol,
                direction=Direction.NEUTRAL,
                confidence=0.0,
                conviction_level=Confidence.LOW,
                key_points=["GEX unavailable"],
                risks=["No gamma exposure data"],
                timeframe="1d",
                evidence={},
                reasoning="Unusual Whales GEX endpoint failed",
            )

        if not evidence:
            gex_report.agent_name = self.name
            return gex_report

        # Directional vote from flow evidence
        bullish = sum(1 for e in evidence if any(k in e.snippet.lower() for k in ("call", "bull", "buy")))
        bearish = sum(1 for e in evidence if any(k in e.snippet.lower() for k in ("put", "bear", "sell")))
        total = bullish + bearish

        if total > 0 and bullish / total > 0.6:
            flow_direction = Direction.LONG
            flow_confidence = min(0.9, 0.5 + (bullish / total) * 0.4)
        elif total > 0 and bearish / total > 0.6:
            flow_direction = Direction.SHORT
            flow_confidence = min(0.9, 0.5 + (bearish / total) * 0.4)
        else:
            flow_direction = Direction.NEUTRAL
            flow_confidence = 0.5

        # Blend with GEX confidence
        final_confidence = (flow_confidence + gex_report.confidence) / 2
        if final_confidence == 0:
            final_confidence = flow_confidence

        conviction = (
            Confidence.HIGH if final_confidence > 0.8
            else Confidence.MEDIUM if final_confidence > 0.5
            else Confidence.LOW
        )

        key_points = [f"Flow signals: {bullish} bullish, {bearish} bearish"]
        key_points.extend([e.snippet[:200] for e in evidence[:5]])
        key_points.extend(gex_report.key_points[:3])

        return AnalystReport(
            agent_name=self.name,
            symbol=symbol,
            direction=flow_direction,
            confidence=round(final_confidence, 2),
            conviction_level=conviction,
            key_points=key_points,
            risks=gex_report.risks + ["Flow can be hedged or misleading"],
            timeframe="1d",
            evidence={"flow_count": len(evidence), "gex": gex_report.evidence.get("raw")},
            reasoning=(
                f"Flow direction {flow_direction.value} with {len(evidence)} signals. "
                f"GEX context: {gex_report.reasoning[:200]}"
            ),
        )
