"""
RSI Oversold/Overbought with EMA Trend Filter

A simple but robust mean reversion strategy.
RSI alone gives false signals in strong trends — the EMA filter fixes that.

Sources:
- Freqtrade strategy repository (multiple RSI variants)
- TradingView Pine Script public library (most copied RSI template)
- QuantConnect Bootcamp 101 (teaching example)

Logic:
- LONG: RSI < 30 AND Price > 200 EMA (only buy dips in uptrends)
- SHORT: RSI > 70 AND Price < 200 EMA (only sell rallies in downtrends)
- Stop: 1.5x ATR
- Target: 2:1 R:R

Best for: Stocks, ETFs, Forex
Timeframe: 1H (swing trading) or 15m (intraday)
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timedelta

from strategies.base import BaseStrategy, Signal


class RSITrendStrategy(BaseStrategy):
    """
    RSI mean reversion with 200 EMA trend filter.
    Simple, robust, works across asset classes.
    """

    name = "rsi_trend"
    description = "RSI oversold/overbought with 200 EMA trend filter. Swing/intraday."
    author = "Community (adapted)"
    source_url = "https://github.com/freqtrade/freqtrade-strategies"

    rsi_period = 14
    rsi_oversold = 30
    rsi_overbought = 70
    ema_trend = 200
    timeframe = "1h"
    risk_reward = 2.0

    def calculate_indicators(self, df) -> Dict[str, Any]:
        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        # Trend EMA
        df["ema_trend"] = df["close"].ewm(span=self.ema_trend, adjust=False).mean()

        # ATR
        import pandas as pd
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

            atr = last["atr"] if not np.isnan(last["atr"]) else last["close"] * 0.01

            # LONG: RSI oversold + price above 200 EMA (uptrend)
            rsi_bounce = last["rsi"] < self.rsi_oversold
            in_uptrend = last["close"] > last["ema_trend"]

            if rsi_bounce and in_uptrend and symbol not in self._positions:
                stop = last["close"] - (atr * 1.5)
                target = last["close"] + (atr * 1.5 * self.risk_reward)

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
                        "rsi": round(last["rsi"], 1),
                        "ema200": round(last["ema_trend"], 2),
                        "trend": "up",
                        "atr": round(atr, 2),
                    },
                    invalidation_price=round(stop, 2),
                    time_stop=datetime.utcnow() + timedelta(days=2),
                ))

            # SHORT: RSI overbought + price below 200 EMA (downtrend)
            rsi_peak = last["rsi"] > self.rsi_overbought
            in_downtrend = last["close"] < last["ema_trend"]

            if rsi_peak and in_downtrend and symbol not in self._positions:
                stop = last["close"] + (atr * 1.5)
                target = last["close"] - (atr * 1.5 * self.risk_reward)

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
                        "rsi": round(last["rsi"], 1),
                        "ema200": round(last["ema_trend"], 2),
                        "trend": "down",
                        "atr": round(atr, 2),
                    },
                    invalidation_price=round(stop, 2),
                    time_stop=datetime.utcnow() + timedelta(days=2),
                ))

        return signals
