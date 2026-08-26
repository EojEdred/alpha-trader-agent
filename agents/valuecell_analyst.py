"""
ValueCell Analyst — Alpha Trader native implementation

Implements the three-agent pattern from ValueCell:
- DeepResearchAgent: fundamental / web / SEC-style research summary
- NewsRetrievalAgent: latest news + sentiment
- StrategyAgent: value / momentum / quality factor score

Produces a single AnalystReport that the ResearchManager can weight alongside
technical, flow, sentiment, and quant analysts.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from agents.base_analyst import BaseAnalyst
from models import EvidenceItem, generate_evidence_id
from models.decision_schemas import AnalystReport, Confidence, Direction
from tools.signal_feed import record_valuecell_signal


try:
    from market_data.providers.massive_provider import MassiveProvider
except ImportError:
    MassiveProvider = None  # type: ignore

try:
    from tools.llm_factory import KimiCLIWrapper
except ImportError:
    KimiCLIWrapper = None  # type: ignore


class ValueCellAnalyst(BaseAnalyst):
    """Fundamental / news / strategy analyst inspired by ValueCell."""

    name = "valuecell_analyst"
    description = "Deep research, news retrieval, and factor scoring via ValueCell patterns"
    default_weight = 0.8

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.provider = MassiveProvider(self.config) if MassiveProvider is not None else None
        self._llm = None

    def _get_llm(self):
        if self._llm is None and KimiCLIWrapper is not None:
            self._llm = KimiCLIWrapper(temperature=0.2)
        return self._llm

    async def analyze(
        self,
        symbol: str,
        price_data: Optional[Dict[str, Any]] = None,
    ) -> AnalystReport:
        """
        Run the ValueCell three-agent pipeline and return an AnalystReport.

        Degrades gracefully if no API key is available.
        """
        symbol = symbol.upper()

        # 1. News retrieval
        news_evidence = await self._news_retrieval(symbol)

        # 2. Deep research (LLM-based synthesis)
        deep_research = await self._deep_research(symbol, news_evidence)

        # 3. Strategy scoring
        score_card = self._strategy_score(symbol, news_evidence, deep_research)

        direction = score_card.get("direction", Direction.NEUTRAL)
        confidence = score_card.get("confidence", 0.5)

        report = AnalystReport(
            agent_name=self.name,
            symbol=symbol,
            direction=direction,
            confidence=round(confidence, 2),
            conviction_level=self._conviction(confidence),
            key_points=deep_research.get("key_points", ["No deep research available"]),
            risks=deep_research.get("risks", ["No fundamental data available"]),
            timeframe="swing",
            evidence={
                "news_count": len(news_evidence),
                "deep_research": deep_research,
                "score_card": score_card,
            },
            reasoning=deep_research.get("summary", f"ValueCell analysis for {symbol}"),
        )

        try:
            await record_valuecell_signal(report)
        except Exception as e:
            logger.warning(f"ValueCellAnalyst: failed to record signal: {e}")

        return report

    async def evidence_for_symbol(self, symbol: str) -> List[EvidenceItem]:
        """Return news evidence items for the symbol."""
        return await self._news_retrieval(symbol)

    # ------------------------------------------------------------------
    # Sub-agents
    # ------------------------------------------------------------------

    async def _news_retrieval(self, symbol: str) -> List[EvidenceItem]:
        """Fetch news via Massive (or any configured news provider)."""
        evidence: List[EvidenceItem] = []
        if self.provider is None or not self.provider.enabled:
            return evidence

        try:
            news = await self.provider.get_news(ticker=symbol, limit=10)
            for article in news.get("results", [])[:5]:
                title = article.get("title", "")
                if not title:
                    continue
                evidence.append(
                    EvidenceItem(
                        id=generate_evidence_id(),
                        url=article.get("article_url", "https://massive.com"),
                        title=f"News: {title}",
                        snippet=article.get("description", title)[:300],
                        timestamp=datetime.utcnow(),
                        confidence=0.7,
                        tags=["valuecell", "news", symbol],
                    )
                )
        except Exception as e:
            logger.debug(f"ValueCell news retrieval failed for {symbol}: {e}")

        return evidence

    async def _deep_research(self, symbol: str, news_evidence: List[EvidenceItem]) -> Dict[str, Any]:
        """Use LLM to synthesize a fundamental/deep-research view."""
        llm = self._get_llm()
        if llm is None:
            return {
                "summary": f"No LLM configured; ValueCell deep research unavailable for {symbol}.",
                "key_points": ["LLM not available"],
                "risks": ["No AI-generated fundamental assessment"],
            }

        news_snippets = "\n".join(
            f"- {e.title}: {e.snippet}" for e in news_evidence[:5]
        ) or "No recent news available."

        prompt = (
            f"You are a value-oriented research analyst. Provide a concise fundamental "
            f"assessment of {symbol} based on the following recent news snippets:\n"
            f"{news_snippets}\n\n"
            f"Return exactly:\n"
            f"SUMMARY: one sentence thesis\n"
            f"KEY_POINTS: bullet list of 3-5 factors\n"
            f"RISKS: bullet list of 2-3 risks\n"
            f"SENTIMENT: bullish | bearish | neutral"
        )

        try:
            from browser_use.llm.messages import UserMessage

            response = await llm.ainvoke([UserMessage(content=prompt)])
            text = response.content if hasattr(response, "content") else str(response)
            return self._parse_research_response(text)
        except Exception as e:
            logger.warning(f"ValueCell deep research LLM failed for {symbol}: {e}")
            return {
                "summary": f"Deep research LLM failed for {symbol}.",
                "key_points": [str(e)],
                "risks": ["LLM error"],
            }

    @staticmethod
    def _parse_research_response(text: str) -> Dict[str, Any]:
        summary_match = re.search(r"SUMMARY:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        sentiment_match = re.search(r"SENTIMENT:\s*(bullish|bearish|neutral)", text, re.IGNORECASE)

        key_points = re.findall(r"[-*]\s*(.+)", text.split("KEY_POINTS:")[1].split("RISKS:")[0]) if "KEY_POINTS:" in text and "RISKS:" in text else []
        risks = re.findall(r"[-*]\s*(.+)", text.split("RISKS:")[1]) if "RISKS:" in text else []

        return {
            "summary": summary_match.group(1).strip() if summary_match else text[:200],
            "key_points": key_points or ["No key points parsed"],
            "risks": risks or ["No risks parsed"],
            "sentiment": sentiment_match.group(1).lower() if sentiment_match else "neutral",
        }

    def _strategy_score(
        self,
        symbol: str,
        news_evidence: List[EvidenceItem],
        deep_research: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Score the symbol on value/momentum/quality factors heuristically."""
        sentiment = deep_research.get("sentiment", "neutral")

        # Count directional words in news snippets
        all_text = " ".join(e.snippet.lower() for e in news_evidence)
        bullish = sum(all_text.count(w) for w in ("beat", "growth", "bull", "upgrade", "strong", "outperform"))
        bearish = sum(all_text.count(w) for w in ("miss", "decline", "bear", "downgrade", "weak", "underperform"))
        total = bullish + bearish

        if sentiment == "bullish" or (total > 0 and bullish / total > 0.6):
            direction = Direction.LONG
            confidence = 0.6 + min(0.25, bullish * 0.02)
        elif sentiment == "bearish" or (total > 0 and bearish / total > 0.6):
            direction = Direction.SHORT
            confidence = 0.6 + min(0.25, bearish * 0.02)
        else:
            direction = Direction.NEUTRAL
            confidence = 0.45

        return {
            "direction": direction,
            "confidence": round(min(confidence, 0.95), 2),
            "value_score": 0.5,
            "momentum_score": round(0.5 + (bullish - bearish) * 0.02, 2),
            "quality_score": 0.5,
            "news_bullish": bullish,
            "news_bearish": bearish,
        }

    @staticmethod
    def _conviction(confidence: float) -> Confidence:
        if confidence > 0.8:
            return Confidence.HIGH
        if confidence > 0.5:
            return Confidence.MEDIUM
        return Confidence.LOW
