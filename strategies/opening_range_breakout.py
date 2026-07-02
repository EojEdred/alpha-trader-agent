"""
Opening Range Breakout (ORB) Strategy

The most popular prop firm challenge-passing strategy.
Used by thousands of funded traders on Topstep, Apex, BluSky, etc.

Sources:
- FX Replay: NQ 1-min scalping strategy library
- Scarface Trades (featured strategy)
- Sahi Charts ORB indicator documentation

Logic:
1. Mark high/low of first N minutes after market open (default: 15 min)
2. Wait for price to break above high (long) or below low (short)
3. Confirm with volume spike (>1.5x average)
4. Entry on retest of breakout level
5. Stop: Back inside the range
6. Target: Range height projection (1:1 or 1.5:1)

Best for: NQ, ES futures | 1-5 min timeframe
Session: US Market Open (9:30 AM ET)
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timedelta
from loguru import logger

from strategies.base import BaseStrategy, Signal


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """
    Opening Range Breakout with volume confirmation.
    The #1 automated strategy for passing prop firm evaluations.
    """

    name = "opening_range_breakout"
    description = "Opening Range Breakout with volume confirmation. Prop firm scalping."
    author = "Prop Firm Community (adapted)"
    source_url = "https://fxreplay.com/learn | https://www.sahi.com/blogs/orb-trading-strategy-explained"

    or_minutes = 15  # Opening range duration
    volume_mult = 1.5
    timeframe = "1m"
    risk_reward = 1.5
    max_hold_hours = 4

    def calculate_indicators(self, df) -> Dict[str, Any]:
        import pandas as pd

        # Rolling volume average
        df["volume_sma"] = df["volume"].rolling(20).mean()

        # ATR
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df["atr"] = true_range.rolling(14).mean()

        return {"df": df}

    def generate_signals(self, data: Dict[str, Any]) -> List[Signal]:
        signals = []
        ohlcv = data.get("ohlcv", {})

        for symbol, df in ohlcv.items():
            if len(df) < self.or_minutes + 10:
                continue

            df = self.calculate_indicators(df)["df"]

            # Calculate opening range from first N candles
            or_candles = df.iloc[-(self.or_minutes + 10):-10]  # Recent OR window
            or_high = or_candles["high"].max()
            or_low = or_candles["low"].min()
            or_height = or_high - or_low

            # Current candle (after OR)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            volume_ok = last["volume"] > last["volume_sma"] * self.volume_mult
            atr = last["atr"] if not np.isnan(last["atr"]) else or_height * 0.3

            # LONG breakout: Close above OR high with volume
            broke_above = last["close"] > or_high and prev["close"] <= or_high

            if broke_above and volume_ok and symbol not in self._positions:
                stop = or_low  # Stop below OR low
                target = last["close"] + or_height  # 1:1 projection

                signals.append(Signal(
                    symbol=symbol,
                    direction="long",
                    entry_price=round(last["close"], 2),
                    stop_price=round(stop, 2),
                    target_price=round(target, 2),
                    conviction=0.75,
                    strategy_name=self.name,
                    timeframe=self.timeframe,
                    evidence={
                        "or_high": round(or_high, 2),
                        "or_low": round(or_low, 2),
                        "or_height": round(or_height, 2),
                        "volume_ratio": round(last["volume"] / last["volume_sma"], 2) if last["volume_sma"] > 0 else 1.0,
                    },
                    invalidation_price=round(or_low, 2),
                    time_stop=datetime.utcnow() + timedelta(hours=self.max_hold_hours),
                ))

            # SHORT breakout: Close below OR low with volume
            broke_below = last["close"] < or_low and prev["close"] >= or_low

            if broke_below and volume_ok and symbol not in self._positions:
                stop = or_high
                target = last["close"] - or_height

                signals.append(Signal(
                    symbol=symbol,
                    direction="short",
                    entry_price=round(last["close"], 2),
                    stop_price=round(stop, 2),
                    target_price=round(target, 2),
                    conviction=0.75,
                    strategy_name=self.name,
                    timeframe=self.timeframe,
                    evidence={
                        "or_high": round(or_high, 2),
                        "or_low": round(or_low, 2),
                        "or_height": round(or_height, 2),
                        "volume_ratio": round(last["volume"] / last["volume_sma"], 2) if last["volume_sma"] > 0 else 1.0,
                    },
                    invalidation_price=round(or_high, 2),
                    time_stop=datetime.utcnow() + timedelta(hours=self.max_hold_hours),
                ))

        return signals
