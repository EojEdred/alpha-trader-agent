"""
Signal Feed — Social / cross-platform copy-trading layer

Captures actionable trade signals from external platforms and Alpha Trader's own
analysts so you can review them in one place and copy them to your venues.

Supported sources:
- TradingView alerts / PhantomFlow webhooks
- Unusual Whales options flow / GEX
- Massive market data & news
- AutoHedge director recommendations
- ValueCell fundamental / news analyst
- Auto-research plans

Usage:
    from tools.signal_feed import SignalFeed
    feed = SignalFeed()
    feed.record_signal(source="tradingview", symbol="ES", direction="long", ...)
    signals = feed.list_signals(limit=50)
"""

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class Signal:
    id: str
    timestamp: str
    source: str
    symbol: str
    direction: str
    confidence: float
    size: Optional[int] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    source_url: Optional[str] = None
    source_id: Optional[str] = None
    rationale: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    copied: bool = False
    copied_at: Optional[str] = None
    intent_id: Optional[str] = None


class SignalFeed:
    """Append-only JSON signal feed with async file locking."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or "data/signals/signals.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"Signal feed read failed: {e}")
            return []

    def _save(self, records: List[Dict[str, Any]]):
        try:
            self.path.write_text(
                json.dumps(records, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Signal feed write failed: {e}")

    async def record_signal(
        self,
        source: str,
        symbol: str,
        direction: str,
        confidence: float = 0.5,
        size: Optional[int] = None,
        entry_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
        source_url: Optional[str] = None,
        source_id: Optional[str] = None,
        rationale: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Signal:
        """Record a new signal."""
        signal = Signal(
            id=str(uuid.uuid4())[:12],
            timestamp=datetime.utcnow().isoformat(),
            source=source,
            symbol=symbol.upper(),
            direction=direction.lower(),
            confidence=max(0.0, min(1.0, confidence)),
            size=size,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            source_url=source_url,
            source_id=source_id,
            rationale=rationale,
            payload=payload or {},
        )

        async with self._lock:
            records = self._load()
            records.append(asdict(signal))
            self._save(records)

        logger.info(f"SignalFeed: recorded {signal.id} {source} {symbol} {direction}")
        return signal

    async def list_signals(
        self,
        source: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> List[Signal]:
        """Return signals newest first."""
        records = self._load()
        signals = [Signal(**r) for r in records]
        signals.sort(key=lambda s: s.timestamp, reverse=True)

        if source:
            signals = [s for s in signals if s.source.lower() == source.lower()]
        if symbol:
            signals = [s for s in signals if s.symbol.upper() == symbol.upper()]

        return signals[:limit]

    async def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Fetch a single signal by id."""
        records = self._load()
        for r in records:
            if r.get("id") == signal_id:
                return Signal(**r)
        return None

    async def mark_copied(self, signal_id: str, intent_id: Optional[str] = None) -> bool:
        """Mark a signal as copied."""
        async with self._lock:
            records = self._load()
            for r in records:
                if r.get("id") == signal_id:
                    r["copied"] = True
                    r["copied_at"] = datetime.utcnow().isoformat()
                    if intent_id:
                        r["intent_id"] = intent_id
                    self._save(records)
                    return True
        return False


# Singleton convenience
_signal_feed: Optional[SignalFeed] = None


def get_signal_feed() -> SignalFeed:
    global _signal_feed
    if _signal_feed is None:
        _signal_feed = SignalFeed()
    return _signal_feed


async def record_plan_signals(
    plans: List[Any],
    source: str = "auto_research",
    source_url: Optional[str] = None,
):
    """Record signals from ResearchPlan objects."""
    feed = get_signal_feed()
    for plan in plans:
        try:
            await feed.record_signal(
                source=source,
                symbol=plan.symbol,
                direction=plan.recommendation.value,
                confidence=plan.confidence,
                source_url=source_url,
                rationale=plan.rationale,
                payload={
                    "analyst_agreement": plan.analyst_agreement,
                    "strategic_actions": plan.strategic_actions,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to record plan signal for {plan.symbol}: {e}")


async def record_autohedge_signals(
    result: Dict[str, Any],
    source_url: Optional[str] = None,
):
    """Record signals from AutoHedge director result."""
    feed = get_signal_feed()
    for rec in result.get("recommendations", []):
        try:
            await feed.record_signal(
                source="autohedge",
                symbol=rec.get("symbol", "UNKNOWN"),
                direction=rec.get("direction", "neutral"),
                confidence=rec.get("confidence", 0.5),
                size=rec.get("size"),
                entry_price=rec.get("entry_price"),
                stop_price=rec.get("stop_loss"),
                target_price=rec.get("take_profit"),
                source_url=source_url,
                rationale=result.get("thesis", ""),
                payload=rec,
            )
        except Exception as e:
            logger.warning(f"Failed to record autohedge signal: {e}")


async def record_valuecell_signal(
    report: Any,
    source_url: Optional[str] = None,
):
    """Record a signal from a ValueCell analyst report."""
    feed = get_signal_feed()
    try:
        await feed.record_signal(
            source="valuecell",
            symbol=report.symbol,
            direction=report.direction.value,
            confidence=report.confidence,
            source_url=source_url,
            rationale=report.reasoning,
            payload={
                "key_points": report.key_points,
                "risks": report.risks,
            },
        )
    except Exception as e:
        logger.warning(f"Failed to record valuecell signal: {e}")
