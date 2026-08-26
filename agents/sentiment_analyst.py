"""
Sentiment Analyst Agent

Combines TradingView news/sentiment, Massive news, and headline analysis
into a single AnalystReport focused on narrative and macro regime.
"""

from typing import Any, Dict, Optional

from loguru import logger

from models.decision_schemas import AnalystReport, Confidence, Direction
from agents.base_analyst import BaseAnalyst
from tools.tradingview_mcp import TradingViewMCP


class SentimentAnalyst(BaseAnalyst):
    """Sentiment and news analyst combining TradingView and macro signals."""

    name = "sentiment_analyst"
    description = "News, social, and macro sentiment analysis"
    default_weight = 0.8

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.tv = TradingViewMCP(self.config)

    async def analyze(
        self,
        symbol: str,
        price_data: Optional[Dict[str, Any]] = None,
    ) -> AnalystReport:
        """
        Analyze news and sentiment for a symbol.

        Uses TradingView's combined TA+news+sentiment tool when available,
        otherwise falls back to bitcoin market pulse for macro context.
        """
        try:
            report = await self.tv.combined_ta_news_sentiment(symbol)
            report.agent_name = self.name
            return report
        except Exception as e:
            logger.warning(f"SentimentAnalyst combined analysis failed for {symbol}: {e}")

        # Fallback: macro pulse
        try:
            pulse = await self.tv.bitcoin_market_pulse()
            if pulse:
                sentiment = "bullish" if "bull" in pulse.snippet.lower() else "bearish" if "bear" in pulse.snippet.lower() else "neutral"
                direction = (
                    Direction.LONG if sentiment == "bullish"
                    else Direction.SHORT if sentiment == "bearish"
                    else Direction.NEUTRAL
                )
                return AnalystReport(
                    agent_name=self.name,
                    symbol=symbol,
                    direction=direction,
                    confidence=pulse.confidence,
                    conviction_level=Confidence.MEDIUM if pulse.confidence > 0.5 else Confidence.LOW,
                    key_points=[pulse.snippet[:300]],
                    risks=["Macro proxy only; not symbol-specific"],
                    timeframe="1d",
                    evidence={"macro_pulse": pulse.to_dict()},
                    reasoning=f"Used macro BTC pulse as proxy: {pulse.snippet[:200]}",
                )
        except Exception as e:
            logger.warning(f"SentimentAnalyst macro pulse failed for {symbol}: {e}")

        return AnalystReport(
            agent_name=self.name,
            symbol=symbol,
            direction=Direction.NEUTRAL,
            confidence=0.0,
            conviction_level=Confidence.LOW,
            key_points=["Sentiment data unavailable"],
            risks=["No news or sentiment source returned data"],
            timeframe="1d",
            evidence={},
            reasoning="Sentiment analysis failed for this symbol.",
        )
