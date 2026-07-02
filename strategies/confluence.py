"""
Analyst Confluence System

Requires multiple strategies/agents to agree before generating a trade signal.
Inspired by TradingAgents' multi-analyst debate.

Usage:
    from strategies.confluence import ConfluenceEngine
    from strategies.registry import StrategyRegistry
    from strategies.data_feed import DataFeed

    registry = StrategyRegistry()
    registry.discover()

    confluence = ConfluenceEngine(registry, min_agreement=2, min_confidence=0.6)
    data = await DataFeed().fetch_multi({"SPY": "schwab", "NQ1!": "schwab"})
    signals = await confluence.run(data)
"""

import asyncio
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from loguru import logger

from strategies.base import Signal
from strategies.registry import StrategyRegistry
from models.decision_schemas import AnalystReport, Direction, Confidence


@dataclass
class ConfluenceResult:
    """Result of confluence analysis for a single symbol."""
    symbol: str
    direction: str
    confidence: float
    agreeing_analysts: List[str]
    disagreeing_analysts: List[str]
    consensus_reached: bool
    raw_signals: List[Signal]


class ConfluenceEngine:
    """
    Runs multiple strategies in parallel and requires agreement before trading.

    Configurable thresholds:
    - min_agreement: How many analysts must agree (default: 2)
    - min_confidence: Minimum confidence score (default: 0.6)
    - agreement_direction: Must agree on direction, or just that there's a signal?
    """

    def __init__(
        self,
        registry: StrategyRegistry,
        min_agreement: int = 2,
        min_confidence: float = 0.6,
        require_direction_match: bool = True,
        strategy_filter: Optional[List[str]] = None,
    ):
        self.registry = registry
        self.min_agreement = min_agreement
        self.min_confidence = min_confidence
        self.require_direction_match = require_direction_match
        self.strategy_filter = strategy_filter  # Only run these strategies

    async def run(self, data: Dict[str, Any]) -> List[ConfluenceResult]:
        """
        Run all strategies, group signals by symbol, check confluence.

        Returns:
            List of ConfluenceResult where consensus_reached=True
        """
        # Run all strategies in parallel
        strategies_to_run = self.strategy_filter or list(self.registry._strategies.keys())

        all_signals: List[Signal] = []
        for name in strategies_to_run:
            try:
                signals = self.registry.run(name, data)
                all_signals.extend(signals)
            except Exception as e:
                logger.error(f"Strategy {name} failed in confluence: {e}")

        if not all_signals:
            return []

        # Group by symbol
        by_symbol: Dict[str, List[Signal]] = {}
        for sig in all_signals:
            by_symbol.setdefault(sig.symbol, []).append(sig)

        results = []
        for symbol, signals in by_symbol.items():
            result = self._evaluate_confluence(symbol, signals)
            if result.consensus_reached:
                results.append(result)
                logger.info(
                    f"Confluence APPROVED for {symbol}: {result.direction} "
                    f"({len(result.agreeing_analysts)}/{len(signals)} analysts, "
                    f"confidence: {result.confidence:.0%})"
                )
            else:
                logger.info(
                    f"Confluence REJECTED for {symbol}: "
                    f"({len(result.agreeing_analysts)}/{len(signals)} agree, "
                    f"need {self.min_agreement})"
                )

        return results

    def _evaluate_confluence(self, symbol: str, signals: List[Signal]) -> ConfluenceResult:
        """Check if enough analysts agree on direction for this symbol."""
        # Filter by minimum confidence
        valid = [s for s in signals if s.conviction >= self.min_confidence]

        if not valid:
            return ConfluenceResult(
                symbol=symbol,
                direction="neutral",
                confidence=0.0,
                agreeing_analysts=[],
                disagreeing_analysts=[s.strategy_name for s in signals],
                consensus_reached=False,
                raw_signals=signals,
            )

        # Count by direction
        longs = [s for s in valid if s.direction == "long"]
        shorts = [s for s in valid if s.direction == "short"]

        # Determine majority direction
        if len(longs) >= self.min_agreement and len(longs) >= len(shorts):
            majority = longs
            direction = "long"
        elif len(shorts) >= self.min_agreement and len(shorts) > len(longs):
            majority = shorts
            direction = "short"
        else:
            # No clear majority
            return ConfluenceResult(
                symbol=symbol,
                direction="neutral",
                confidence=0.0,
                agreeing_analysts=[],
                disagreeing_analysts=[s.strategy_name for s in valid],
                consensus_reached=False,
                raw_signals=signals,
            )

        # Calculate weighted confidence (higher conviction = more weight)
        total_confidence = sum(s.conviction for s in majority)
        avg_confidence = total_confidence / len(majority)

        agreeing = [s.strategy_name for s in majority]
        disagreeing = [s.strategy_name for s in valid if s not in majority]

        return ConfluenceResult(
            symbol=symbol,
            direction=direction,
            confidence=avg_confidence,
            agreeing_analysts=agreeing,
            disagreeing_analysts=disagreeing,
            consensus_reached=True,
            raw_signals=signals,
        )

    def to_analyst_reports(self, result: ConfluenceResult) -> List[AnalystReport]:
        """Convert confluence signals to structured AnalystReport objects."""
        reports = []
        for signal in result.raw_signals:
            confidence_level = Confidence.HIGH if signal.conviction > 0.8 else (
                Confidence.MEDIUM if signal.conviction > 0.5 else Confidence.LOW
            )
            reports.append(AnalystReport(
                agent_name=signal.strategy_name,
                symbol=signal.symbol,
                direction=Direction.LONG if signal.direction == "long" else Direction.SHORT,
                confidence=signal.conviction,
                conviction_level=confidence_level,
                key_points=[f"Entry: {signal.entry_price}", f"Stop: {signal.stop_price}", f"Target: {signal.target_price}"],
                risks=[f"Invalidation at {signal.invalidation_price}"],
                timeframe=signal.timeframe,
                evidence=signal.evidence,
                reasoning=f"Signal generated by {signal.strategy_name} with conviction {signal.conviction}",
            ))
        return reports

    def to_trade_intents(self, results: List[ConfluenceResult]) -> List["TradeIntent"]:
        """Convert confluence results to TradeIntents for execution."""
        from models import TradeIntent, generate_intent_id
        from datetime import datetime, timedelta

        intents = []
        for result in results:
            if not result.consensus_reached:
                continue

            # Use the highest-confidence signal from the majority
            majority_signals = [s for s in result.raw_signals if s.direction == result.direction]
            best_signal = max(majority_signals, key=lambda s: s.conviction)

            intent = TradeIntent(
                id=generate_intent_id(),
                capsule_id="confluence",
                thesis_id=f"confluence_{result.direction}",
                symbol=result.symbol,
                direction=result.direction,
                entry_price=best_signal.entry_price,
                stop_price=best_signal.stop_price,
                target_price=best_signal.target_price,
                conviction=result.confidence,
                invalidation_price=best_signal.invalidation_price,
                time_stop=datetime.utcnow() + timedelta(hours=4),
                risk_reward_ratio=abs(best_signal.target_price - best_signal.entry_price) / abs(best_signal.entry_price - best_signal.stop_price)
                if best_signal.entry_price != best_signal.stop_price else 2.0,
                size=1,
                venue="schwab",  # Default, will be overridden by router
                evidence_citations=[f"confluence:{a}" for a in result.agreeing_analysts],
            )
            intents.append(intent)

        return intents
