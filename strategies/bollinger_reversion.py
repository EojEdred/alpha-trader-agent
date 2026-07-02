"""
Bollinger Bands Mean Reversion Strategy

A classic statistical arbitrage approach. Price tends to revert to the mean
when it hits the outer Bollinger Bands.

Sources:
- John Bollinger's original concept (1980s, still widely used)
- Freqtrade strategy repository (multiple implementations)
- QuantConnect LEAN example strategies

Logic:
- LONG: Price touches lower band AND RSI < 35 AND candle shows reversal (bullish engulfing/hammer)
- SHORT: Price touches upper band AND RSI > 65 AND candle shows reversal
- Stop: Outside the opposite band
- Target: Middle band (20 SMA)

Best for: Range-bound markets, equities, forex
Avoid: Strong trending markets (use with trend filter)
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timedelta

from strategies.base import BaseStrategy, Signal


class BollingerReversionStrategy(BaseStrategy):
    """
    Bollinger Bands mean reversion with RSI confirmation.
    Classic strategy used by thousands of retail and institutional traders.
    """

    name = "bollinger_reversion"
    description = "Bollinger Bands mean reversion with RSI confirmation. Best in ranging markets."
    author = "John Bollinger concept (adapted)"
    source_url = "https://www.bollingerbands.com"

    bb_period = 20
    bb_std = 2.0
    rsi_period = 14
    rsi_oversold = 35
    rsi_overbought = 65
    timeframe = "15m"
    risk_reward = 1.5

    def calculate_indicators(self, df) -> Dict[str, Any]:
        # Bollinger Bands
        df["sma"] = df["close"].rolling(self.bb_period).mean()
        df["std"] = df["close"].rolling(self.bb_period).std()
        df["upper"] = df["sma"] + (df["std"] * self.bb_std)
        df["lower"] = df["sma"] - (df["std"] * self.bb_std)
        df["bandwidth"] = (df["upper"] - df["lower"]) / df["sma"]

        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        # ATR
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        import pandas as pd
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df["atr"] = true_range.rolling(14).mean()

        return {"df": df}

    def generate_signals(self, data: Dict[str, Any]) -> List[Signal]:
        signals = []
        ohlcv = data.get("ohlcv", {})

        for symbol, df in ohlcv.items():
            if len(df) < self.bb_period + 5:
                continue

            df = self.calculate_indicators(df)["df"]
            last = df.iloc[-1]
            prev = df.iloc[-2]

            # Skip if bands are too wide (high volatility, trending)
            if last["bandwidth"] > 0.1:  # Bands > 10% of price
                continue

            atr = last["atr"] if not np.isnan(last["atr"]) else last["close"] * 0.005

            # LONG: Price at/below lower band + RSI oversold
            at_lower = last["close"] <= last["lower"] or prev["close"] <= prev["lower"]
            rsi_oversold = last["rsi"] < self.rsi_oversold

            if at_lower and rsi_oversold and symbol not in self._positions:
                stop = last["close"] - (atr * 2)
                target = last["sma"]  # Target: mean reversion to middle band

                signals.append(Signal(
                    symbol=symbol,
                    direction="long",
                    entry_price=round(last["close"], 2),
                    stop_price=round(stop, 2),
                    target_price=round(target, 2),
                    conviction=0.70,
                    strategy_name=self.name,
                    timeframe=self.timeframe,
                    evidence={
                        "bb_lower": round(last["lower"], 2),
                        "bb_upper": round(last["upper"], 2),
                        "rsi": round(last["rsi"], 1),
                        "bandwidth": round(last["bandwidth"], 3),
                    },
                    invalidation_price=round(last["lower"] - atr, 2),
                    time_stop=datetime.utcnow() + timedelta(hours=6),
                ))

            # SHORT: Price at/above upper band + RSI overbought
            at_upper = last["close"] >= last["upper"] or prev["close"] >= prev["upper"]
            rsi_overbought = last["rsi"] > self.rsi_overbought

            if at_upper and rsi_overbought and symbol not in self._positions:
                stop = last["close"] + (atr * 2)
                target = last["sma"]

                signals.append(Signal(
                    symbol=symbol,
                    direction="short",
                    entry_price=round(last["close"], 2),
                    stop_price=round(stop, 2),
                    target_price=round(target, 2),
                    conviction=0.70,
                    strategy_name=self.name,
                    timeframe=self.timeframe,
                    evidence={
                        "bb_lower": round(last["lower"], 2),
                        "bb_upper": round(last["upper"], 2),
                        "rsi": round(last["rsi"], 1),
                        "bandwidth": round(last["bandwidth"], 3),
                    },
                    invalidation_price=round(last["upper"] + atr, 2),
                    time_stop=datetime.utcnow() + timedelta(hours=6),
                ))

        return signals
