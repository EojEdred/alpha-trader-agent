"""
Massive Analyst Agent

Turns Massive API market data (OHLCV, snapshots, news) into a standardized
AnalystReport and EvidenceItem so the ResearchManager can weight it alongside
technical, flow, sentiment, and quant analysts.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from agents.base_analyst import BaseAnalyst
from market_data.providers.massive_provider import MassiveProvider
from models import EvidenceItem, generate_evidence_id
from models.decision_schemas import AnalystReport, Confidence, Direction


class MassiveAnalyst(BaseAnalyst):
    """Fundamental / market-data analyst powered by the Massive API."""

    name = "massive_analyst"
    description = "Price-action, volume, and news analysis via the Massive API"
    default_weight = 0.9

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.provider = MassiveProvider(self.config)

    async def analyze(
        self,
        symbol: str,
        price_data: Optional[Dict[str, Any]] = None,
    ) -> AnalystReport:
        """
        Analyze a symbol using Massive OHLCV and snapshot data.

        Returns a low-confidence neutral report if Massive is disabled or the
        request fails, so ResearchManager synthesis can continue.
        """
        symbol = symbol.upper()
        ohlcv = await self.provider.get_ohlcv(symbol, multiplier=1, timespan="day", days=20)
        snapshot = await self.provider.get_snapshot(symbol)

        if ohlcv is None and snapshot is None:
            return self._disabled_report(symbol)

        candles = ohlcv.get("candles", []) if ohlcv else []
        current = self._extract_current_price(snapshot, candles)

        direction, confidence, key_points, risks = self._evaluate(candles, snapshot, current)

        evidence = {
            "source": "massive",
            "candles_count": len(candles),
            "current_price": current,
            "snapshot": snapshot,
        }

        return AnalystReport(
            agent_name=self.name,
            symbol=symbol,
            direction=direction,
            confidence=round(confidence, 2),
            conviction_level=self._conviction(confidence),
            key_points=key_points,
            risks=risks,
            timeframe="swing",
            evidence=evidence,
            reasoning=(
                f"Massive data for {symbol}: price={current}, "
                f"{'bullish' if direction == Direction.LONG else 'bearish' if direction == Direction.SHORT else 'neutral'} "
                f"bias with {len(candles)} daily candles examined."
            ),
        )

    async def evidence_for_symbol(self, symbol: str) -> List[EvidenceItem]:
        """Return EvidenceItem objects for Massive-derived data."""
        symbol = symbol.upper()
        evidence: List[EvidenceItem] = []

        # Price / snapshot evidence
        try:
            snapshot = await self.provider.get_snapshot(symbol)
            if snapshot:
                ticker = snapshot.get("ticker", symbol)
                last = self._extract_current_price(snapshot, [])
                evidence.append(
                    EvidenceItem(
                        id=generate_evidence_id(),
                        url=f"https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
                        title=f"Massive snapshot: {ticker}",
                        snippet=f"Last price {last} from Massive snapshot.",
                        timestamp=datetime.utcnow(),
                        confidence=0.85,
                        tags=["massive", "snapshot", ticker],
                    )
                )
        except Exception as e:
            logger.debug(f"Massive snapshot evidence failed for {symbol}: {e}")

        # News evidence
        try:
            news = await self.provider.get_news(ticker=symbol, limit=5)
            if news:
                for article in news.get("results", [])[:3]:
                    title = article.get("title", "")
                    if not title:
                        continue
                    evidence.append(
                        EvidenceItem(
                            id=generate_evidence_id(),
                            url=article.get("article_url", "https://massive.com"),
                            title=f"Massive news: {title}",
                            snippet=article.get("description", title)[:300],
                            timestamp=datetime.utcnow(),
                            confidence=0.7,
                            tags=["massive", "news", symbol],
                        )
                    )
        except Exception as e:
            logger.debug(f"Massive news evidence failed for {symbol}: {e}")

        return evidence

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_current_price(snapshot: Optional[Dict[str, Any]], candles: List[Dict[str, Any]]) -> Optional[float]:
        if snapshot:
            ticker = snapshot.get("ticker")
            day = snapshot.get("day", {})
            last = day.get("c") or snapshot.get("lastTrade", {}).get("p")
            if last is not None:
                return float(last)
            # Try minutely last quote
            last_quote = snapshot.get("lastQuote", {})
            if "P" in last_quote and "p" in last_quote:
                return (float(last_quote["P"]) + float(last_quote["p"])) / 2.0
        if candles:
            return float(candles[-1].get("close", 0))
        return None

    def _evaluate(
        self,
        candles: List[Dict[str, Any]],
        snapshot: Optional[Dict[str, Any]],
        current: Optional[float],
    ):
        key_points: List[str] = []
        risks: List[str] = []

        if current is None or len(candles) < 2:
            return Direction.NEUTRAL, 0.3, ["Insufficient Massive data"], ["Data unavailable"]

        closes = [float(c["close"]) for c in candles if c.get("close") is not None]
        prev_close = closes[-2]
        change_pct = (current - prev_close) / prev_close if prev_close else 0.0

        # Simple 5-day vs 10-day momentum
        sma5 = sum(closes[-5:]) / len(closes[-5:]) if len(closes) >= 5 else None
        sma10 = sum(closes[-10:]) / len(closes[-10:]) if len(closes) >= 10 else None

        volumes = [int(c.get("volume", 0) or 0) for c in candles]
        avg_volume = sum(volumes[:-1]) / max(len(volumes) - 1, 1) if len(volumes) > 1 else 0
        latest_volume = volumes[-1] if volumes else 0
        volume_surge = latest_volume > avg_volume * 1.5 if avg_volume else False

        key_points.append(f"Current price {current:.2f} vs prior close {prev_close:.2f} ({change_pct:+.2%})")
        if sma5 and sma10:
            key_points.append(f"5-day SMA {sma5:.2f} vs 10-day SMA {sma10:.2f}")
        if volume_surge:
            key_points.append(f"Volume surge: {latest_volume:,} vs {avg_volume:,.0f} avg")

        # Direction logic
        bullish_signals = 0
        bearish_signals = 0

        if change_pct > 0.005:
            bullish_signals += 1
        elif change_pct < -0.005:
            bearish_signals += 1

        if sma5 and sma10:
            if sma5 > sma10:
                bullish_signals += 1
            else:
                bearish_signals += 1

        if volume_surge and change_pct > 0:
            bullish_signals += 1
        elif volume_surge and change_pct < 0:
            bearish_signals += 1

        if bullish_signals > bearish_signals:
            direction = Direction.LONG
            confidence = 0.5 + min(0.15 * bullish_signals, 0.35)
        elif bearish_signals > bullish_signals:
            direction = Direction.SHORT
            confidence = 0.5 + min(0.15 * bearish_signals, 0.35)
        else:
            direction = Direction.NEUTRAL
            confidence = 0.45

        risks.append("Massive signal is based on price/volume only; does not capture options flow or sentiment")
        risks.append("Data delays or snapshot gaps can change the picture quickly")

        return direction, confidence, key_points, risks

    @staticmethod
    def _conviction(confidence: float) -> Confidence:
        if confidence > 0.8:
            return Confidence.HIGH
        if confidence > 0.5:
            return Confidence.MEDIUM
        return Confidence.LOW

    @staticmethod
    def _disabled_report(symbol: str) -> AnalystReport:
        return AnalystReport(
            agent_name=MassiveAnalyst.name,
            symbol=symbol.upper(),
            direction=Direction.NEUTRAL,
            confidence=0.0,
            conviction_level=Confidence.LOW,
            key_points=["Massive API disabled or no data returned"],
            risks=["No Massive data available"],
            timeframe="swing",
            evidence={},
            reasoning="Massive provider is not configured or returned no data; skipping.",
        )
