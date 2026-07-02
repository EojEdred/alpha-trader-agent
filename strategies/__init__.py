"""
Alpha Trader Strategy Library

Trusted open-source strategies adapted for multi-venue execution:
- OANDA (forex, gold, CFDs)
- Schwab API (stocks, ETFs, options)
- ThinkOrSwim Desktop (futures)
- Prop Firm Browser (Topstep, Apex, etc.)

Usage:
    from strategies import StrategyRegistry, DataFeed
    from strategies.ema_cross import EMACrossHeikinStrategy

    registry = StrategyRegistry()
    registry.discover()

    feed = DataFeed()
    data = await feed.fetch_multi({"SPY": "schwab", "NQ1!": "schwab"})
    signals = registry.run("vwap_trend", data)
"""

from strategies.base import BaseStrategy, Signal
from strategies.registry import StrategyRegistry
from strategies.data_feed import DataFeed

__all__ = [
    "BaseStrategy",
    "Signal",
    "StrategyRegistry",
    "DataFeed",
]
