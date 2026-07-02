"""
Base Strategy Class

All strategies inherit from this. Provides common interface for:
- Indicator calculation
- Signal generation
- Position sizing
- Risk management hooks

Usage:
    from strategies.base import BaseStrategy

    class MyStrategy(BaseStrategy):
        def generate_signals(self, data) -> List[TradeIntent]:
            ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from loguru import logger


try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    logger.warning("TA-Lib not installed. Some strategies will use fallback calculations.")


@dataclass
class Signal:
    """A raw trading signal from a strategy."""
    symbol: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_price: float
    target_price: float
    conviction: float  # 0.0 to 1.0
    strategy_name: str
    timeframe: str
    evidence: Dict[str, Any]
    invalidation_price: Optional[float] = None
    time_stop: Optional[datetime] = None


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Subclasses must implement:
        - generate_signals(data) -> List[Signal]

    Optional overrides:
        - calculate_indicators(data) -> Dict
        - should_trade(symbol, signal) -> bool
    """

    name: str = "base"
    description: str = ""
    author: str = ""
    source_url: str = ""

    # Default parameters (override in subclass)
    timeframe: str = "5m"
    risk_per_trade_pct: float = 1.0
    max_positions: int = 5
    min_conviction: float = 0.5

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._positions: Dict[str, Any] = {}  # Track active positions
        self._indicators: Dict[str, Any] = {}

    @abstractmethod
    def generate_signals(self, data: Dict[str, Any]) -> List[Signal]:
        """
        Generate trading signals from market data.

        Args:
            data: Dict with keys like 'ohlcv', 'quotes', etc.
                  ohlcv format: {symbol: pd.DataFrame with open, high, low, close, volume}

        Returns:
            List of Signal objects
        """
        pass

    def calculate_indicators(self, df) -> Dict[str, Any]:
        """
        Calculate technical indicators for a single symbol's OHLCV DataFrame.

        Override in subclass to add custom indicators.
        """
        return {}

    def should_trade(self, symbol: str, signal: Signal) -> bool:
        """
        Filter signals before they become TradeIntents.

        Override for custom filtering (e.g., avoid earnings, news events).
        """
        if signal.conviction < self.min_conviction:
            return False
        if len(self._positions) >= self.max_positions:
            return False
        return True

    def to_trade_intent(self, signal: Signal, venue: str = "schwab") -> "TradeIntent":
        """Convert a Signal to a TradeIntent for execution."""
        from models import TradeIntent, generate_intent_id

        return TradeIntent(
            id=generate_intent_id(),
            capsule_id=self.name,
            thesis_id=signal.strategy_name,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            target_price=signal.target_price,
            conviction=signal.conviction,
            invalidation_price=signal.invalidation_price or signal.stop_price,
            time_stop=signal.time_stop or (datetime.utcnow() + timedelta(hours=4)),
            risk_reward_ratio=abs(signal.target_price - signal.entry_price) / abs(signal.entry_price - signal.stop_price)
            if signal.entry_price != signal.stop_price else 2.0,
            size=1,  # Sized by PortfolioBrain
            venue=venue,
            evidence_citations=[f"{self.name}:{k}={v}" for k, v in signal.evidence.items()],
        )

    def on_fill(self, symbol: str, fill_price: float, direction: str):
        """Called when a trade is filled. Track active positions."""
        self._positions[symbol] = {
            "entry": fill_price,
            "direction": direction,
            "time": datetime.utcnow(),
        }

    def on_exit(self, symbol: str):
        """Called when a position is closed."""
        self._positions.pop(symbol, None)

    @classmethod
    def info(cls) -> Dict[str, str]:
        return {
            "name": cls.name,
            "description": cls.description,
            "author": cls.author,
            "source": cls.source_url,
        }
