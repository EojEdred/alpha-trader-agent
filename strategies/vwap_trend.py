"""
VWAP + EMA Trend Following Strategy

Sources:
- FX Replay strategy library (most popular futures strategy)
- PickMyTrade prop firm automation (3M+ trades)
- FundedNest Anchored VWAP guide

Logic:
- LONG: Price > VWAP AND Price > 21 EMA AND Volume > 1.3x average
- SHORT: Price < VWAP AND Price < 21 EMA AND Volume > 1.3x average
- Stop: 1x ATR or VWAP breach
- Target: 2:1 R:R minimum

Timeframe: 5m (intraday scalping)
Best for: NQ, ES, CL, GC futures | SPY, QQQ equities
"""

import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timedelta

from strategies.base import BaseStrategy, Signal


class VWAPTrendStrategy(BaseStrategy):
    """
    VWAP + EMA trend following with volume confirmation.
    The most-cited automated strategy for prop firm futures trading.
    """

    name = "vwap_trend"
    description = "VWAP + 21 EMA trend following with volume confirmation. Intraday scalping."
    author = "Prop Firm Community (adapted)"
    source_url = "https://fxreplay.com/learn | https://blog.pickmytrade.io"

    ema_period = 21
    volume_mult = 1.3
    timeframe = "5m"
    risk_reward = 2.0
    atr_period = 14

    def calculate_indicators(self, df) -> Dict[str, Any]:
        import pandas as pd

        # VWAP = cumulative(TP * Volume) / cumulative(Volume)
        tp = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (tp * df["volume"]).cumsum() / df["volume"].cumsum()

        # EMA
        df["ema"] = df["close"].ewm(span=self.ema_period, adjust=False).mean()

        # Volume average
        df["volume_sma"] = df["volume"].rolling(20).mean()

        # ATR
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df["atr"] = true_range.rolling(self.atr_period).mean()

        return {"df": df}

    def generate_signals(self, data: Dict[str, Any]) -> List[Signal]:
        signals = []
        ohlcv = data.get("ohlcv", {})

        for symbol, df in ohlcv.items():
            if len(df) < max(self.ema_period, self.atr_period) + 5:
                continue

            df = self.calculate_indicators(df)["df"]
            last = df.iloc[-1]
            prev = df.iloc[-2]

            # Volume confirmation
            volume_ok = last["volume"] > last["volume_sma"] * self.volume_mult

            # LONG: Price > VWAP + Price > EMA21 + Volume spike
            if last["close"] > last["vwap"] and last["close"] > last["ema"] and volume_ok:
                # Avoid duplicate signals - only signal on cross or first touch
                was_below = prev["close"] <= prev["vwap"] or prev["close"] <= prev["ema"]

                if was_below or symbol not in self._positions:
                    atr = last["atr"] if not np.isnan(last["atr"]) else last["close"] * 0.003
                    stop = last["close"] - atr
                    target = last["close"] + (atr * self.risk_reward)

                    signals.append(Signal(
                        symbol=symbol,
                        direction="long",
                        entry_price=round(last["close"], 2),
                        stop_price=round(stop, 2),
                        target_price=round(target, 2),
                        conviction=0.80 if volume_ok else 0.65,
                        strategy_name=self.name,
                        timeframe=self.timeframe,
                        evidence={
                            "vwap": round(last["vwap"], 2),
                            "ema21": round(last["ema"], 2),
                            "volume_ratio": round(last["volume"] / last["volume_sma"], 2) if last["volume_sma"] > 0 else 1.0,
                            "atr": round(atr, 2),
                        },
                        invalidation_price=round(last["vwap"], 2),
                        time_stop=datetime.utcnow() + timedelta(hours=2),
                    ))

            # SHORT: Price < VWAP + Price < EMA21 + Volume spike
            elif last["close"] < last["vwap"] and last["close"] < last["ema"] and volume_ok:
                was_above = prev["close"] >= prev["vwap"] or prev["close"] >= prev["ema"]

                if was_above or symbol not in self._positions:
                    atr = last["atr"] if not np.isnan(last["atr"]) else last["close"] * 0.003
                    stop = last["close"] + atr
                    target = last["close"] - (atr * self.risk_reward)

                    signals.append(Signal(
                        symbol=symbol,
                        direction="short",
                        entry_price=round(last["close"], 2),
                        stop_price=round(stop, 2),
                        target_price=round(target, 2),
                        conviction=0.80 if volume_ok else 0.65,
                        strategy_name=self.name,
                        timeframe=self.timeframe,
                        evidence={
                            "vwap": round(last["vwap"], 2),
                            "ema21": round(last["ema"], 2),
                            "volume_ratio": round(last["volume"] / last["volume_sma"], 2) if last["volume_sma"] > 0 else 1.0,
                            "atr": round(atr, 2),
                        },
                        invalidation_price=round(last["vwap"], 2),
                        time_stop=datetime.utcnow() + timedelta(hours=2),
                    ))

        return signals
