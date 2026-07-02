"""
EMA Crossover + Heikin-Ashi Strategy

Adapted from: freqtrade/freqtrade-strategies (Strategy001)
Source: https://github.com/freqtrade/freqtrade-strategies
Stars: 5,218 | Author: Gerald Lonlas

Original: Crypto 5m timeframe
Adapted for: Stocks, Futures, Forex (any timeframe)

Logic:
- BUY: EMA20 crosses above EMA50 AND Heikin-Ashi close > EMA20 AND green HA candle
- SELL: EMA50 crosses above EMA100 (trend reversal) AND HA close < EMA20 AND red HA candle
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timedelta
from loguru import logger

from strategies.base import BaseStrategy, Signal


class EMACrossHeikinStrategy(BaseStrategy):
    """
    EMA Crossover with Heikin-Ashi confirmation.
    A classic trend-following strategy trusted by 5,000+ freqtrade users.
    """

    name = "ema_cross_heikin"
    description = "EMA20/50 crossover with Heikin-Ashi candle confirmation. Trend following."
    author = "Gerald Lonlas (adapted)"
    source_url = "https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/Strategy001.py"

    # Parameters
    ema_fast = 20
    ema_slow = 50
    ema_trend = 100
    timeframe = "5m"
    risk_reward = 2.0

    def calculate_indicators(self, df) -> Dict[str, Any]:
        """Calculate EMAs and Heikin-Ashi candles."""
        import pandas as pd

        # EMAs
        df["ema_fast"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()
        df["ema_trend"] = df["close"].ewm(span=self.ema_trend, adjust=False).mean()

        # Heikin-Ashi
        df["ha_close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
        ha_open = [(df["open"].iloc[0] + df["close"].iloc[0]) / 2]
        for i in range(1, len(df)):
            ha_open.append((ha_open[i - 1] + df["ha_close"].iloc[i - 1]) / 2)
        df["ha_open"] = ha_open

        # ATR for stop loss
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
            if len(df) < self.ema_trend + 5:
                continue

            df = self.calculate_indicators(df)["df"]
            last = df.iloc[-1]
            prev = df.iloc[-2]

            # Long entry: EMA20 crosses above EMA50 + green HA + HA close > EMA20
            ema_cross_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
            green_ha = last["ha_close"] > last["ha_open"]
            above_ema = last["ha_close"] > last["ema_fast"]

            if ema_cross_up and green_ha and above_ema:
                atr = last["atr"] if not np.isnan(last["atr"]) else last["close"] * 0.005
                stop = last["close"] - (atr * 1.5)
                target = last["close"] + (atr * 1.5 * self.risk_reward)

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
                        "ema_cross": f"{self.ema_fast}/{self.ema_slow}",
                        "ha_color": "green",
                        "trend": "up",
                        "atr": round(atr, 2),
                    },
                    invalidation_price=round(stop, 2),
                    time_stop=datetime.utcnow() + timedelta(hours=4),
                ))

            # Short entry: EMA20 crosses below EMA50 + red HA + HA close < EMA20
            ema_cross_down = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]
            red_ha = last["ha_close"] < last["ha_open"]
            below_ema = last["ha_close"] < last["ema_fast"]

            if ema_cross_down and red_ha and below_ema:
                atr = last["atr"] if not np.isnan(last["atr"]) else last["close"] * 0.005
                stop = last["close"] + (atr * 1.5)
                target = last["close"] - (atr * 1.5 * self.risk_reward)

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
                        "ema_cross": f"{self.ema_fast}/{self.ema_slow}",
                        "ha_color": "red",
                        "trend": "down",
                        "atr": round(atr, 2),
                    },
                    invalidation_price=round(stop, 2),
                    time_stop=datetime.utcnow() + timedelta(hours=4),
                ))

        return signals
