#!/usr/bin/env python3
"""
Regime-aware signal overlay for the Alpha Trader focus universe.

Implements items #2, #3 and #4 from the regime-aware stat-arb checklist:
  #2  Assume multiple equilibriums — each regime (bull / bear / range) has its
      own mean and volatility.
  #3  Trade probabilities, not predictions — only emit a signal when the
      current-regime probability exceeds a threshold.
  #4  Measure deviations inside the regime — z-scores are computed relative to
      the current regime's mean and std, not a single long-term average.

Item #1 (regime detection itself) is intentionally left as a simple, robust
classifier. It can be swapped for a Hamilton filter / HMM later without changing
the rest of the overlay.
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
    if len(df) < period + 1:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


def _compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
    if len(df) < period * 2 + 1:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    plus_dm = (high - prev_high).where((high - prev_high) > (prev_low - low), 0.0).clip(lower=0)
    minus_dm = (prev_low - low).where((prev_low - low) > (high - prev_high), 0.0).clip(lower=0)

    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / period, min_periods=period).mean()


def _compute_rsi(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
    if len(df) < period + 1:
        return None
    close = df["close"].astype(float)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


class RegimeAnalyzer:
    """
    Detect the current market regime and compute regime-relative z-scores.

    Regimes:
      - bull  : price above rising moving averages with decent trend strength
      - bear  : price below falling moving averages with decent trend strength
      - range : everything else

    The confidence of the regime is normalized to [0, 1] and can be used as the
    probability required by item #3.
    """

    def __init__(
        self,
        adx_period: int = 14,
        short_ma: int = 20,
        long_ma: int = 50,
        regime_lookback: int = 60,
        min_regime_bars: int = 10,
        confidence_threshold: float = 0.60,
    ):
        self.adx_period = adx_period
        self.short_ma = short_ma
        self.long_ma = long_ma
        self.regime_lookback = regime_lookback
        self.min_regime_bars = min_regime_bars
        self.confidence_threshold = confidence_threshold

    def _require_bars(self) -> int:
        return max(self.long_ma, self.adx_period * 2) + 5

    def _score_regimes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame indexed like df with bull/bear/range scores."""
        close = df["close"].astype(float)
        sma_short = close.rolling(window=self.short_ma, min_periods=self.short_ma).mean()
        sma_long = close.rolling(window=self.long_ma, min_periods=self.long_ma).mean()
        atr = _compute_atr(df, period=self.adx_period)
        adx = _compute_adx(df, period=self.adx_period)

        # Normalise distances by ATR so the scores are comparable across symbols.
        d_short = (close - sma_short) / atr
        d_long = (close - sma_long) / atr
        slope = (sma_short - sma_long) / atr

        # Trend strength scaled so ADX = 25 -> 0.25, ADX = 55 -> 1.0.
        trend_strength = ((adx - 15.0) / 40.0).clip(lower=0.0, upper=1.0)

        bull = (
            (d_short > 0).astype(float) * 0.30
            + (d_long > 0).astype(float) * 0.30
            + (slope > 0).astype(float) * 0.20
            + trend_strength * 0.20
        )
        bear = (
            (d_short < 0).astype(float) * 0.30
            + (d_long < 0).astype(float) * 0.30
            + (slope < 0).astype(float) * 0.20
            + trend_strength * 0.20
        )
        # Range is the residual confidence not captured by bull or bear.
        range_score = (1.0 - bull.clip(upper=1.0) - bear.clip(upper=1.0)).clip(lower=0.0)

        scores = pd.DataFrame(
            {"bull": bull, "bear": bear, "range": range_score},
            index=df.index,
        )
        return scores

    def analyze(self, df: pd.DataFrame) -> Optional[Dict[str, any]]:
        """Return the current regime, confidence, and z-score for the latest bar."""
        if len(df) < self._require_bars():
            return None

        scores = self._score_regimes(df)
        # Early bars may be all-NaN because the indicators need warmup. Treat them
        # as 'range' so pandas idxmax does not raise on an all-NA row.
        labels = scores.apply(
            lambda row: row.idxmax() if not row.isna().all() else "range", axis=1
        )
        latest = scores.iloc[-1]
        regime = latest.idxmax()
        confidence = float(latest[regime])

        # Regime-relative mean / std using only bars classified into the same regime.
        recent = df.iloc[-self.regime_lookback :].copy()
        recent["regime"] = labels.iloc[-self.regime_lookback :]
        same_regime = recent[recent["regime"] == regime]
        if len(same_regime) < self.min_regime_bars:
            return None

        prices = same_regime["close"].astype(float)
        regime_mean = float(prices.mean())
        regime_std = float(prices.std())
        if regime_std <= 0 or not np.isfinite(regime_std):
            return None

        price = float(df["close"].iloc[-1])
        z_score = (price - regime_mean) / regime_std

        rsi = _compute_rsi(df)
        current_rsi = float(rsi.iloc[-1]) if rsi is not None else None

        return {
            "regime": regime,
            "confidence": round(confidence, 3),
            "z_score": round(z_score, 3),
            "regime_mean": round(regime_mean, 4),
            "regime_std": round(regime_std, 4),
            "rsi": round(current_rsi, 2) if current_rsi is not None else None,
        }


def _pullback_stop_target(
    df: pd.DataFrame,
    direction: str,
    sma_long: float,
) -> Tuple[Optional[float], Optional[float]]:
    """Stop and target for a pullback-to-regime trade."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    if direction == "long":
        recent_low = float(low.tail(10).min())
        stop = max(recent_low * 0.998, sma_long * 0.995)
        target = float(high.tail(20).max())
    else:  # short
        recent_high = float(high.tail(10).max())
        stop = min(recent_high * 1.002, sma_long * 1.005)
        target = float(low.tail(20).min())
    return stop, target


def regime_aware_pullback_signal(
    symbol: str,
    df: pd.DataFrame,
    current_price: Optional[float] = None,
    min_confidence: float = 0.60,
    z_threshold: float = 0.30,
    min_rr: float = 2.0,
) -> Optional[Dict[str, any]]:
    """
    Generate a pullback-to-regime signal for SPY, QQQ, ES, NQ and TSLA.

    Logic:
      - Bull regime + high confidence  -> look for long pullback (z <= -z_threshold)
      - Bear regime + high confidence  -> look for short rally    (z >= +z_threshold)
      - Range / uncertain regime       -> no directional signal

    The signal uses the current regime's own mean and volatility, so a "pullback"
    is measured relative to the active equilibrium, not a fixed long-term average.
    A short-term 20-SMA deviation overlay catches shallow pullbacks in steady
    uptrends (e.g. SPY) without weakening the core filter.
    """
    if symbol not in ("SPY", "QQQ", "ES", "NQ", "TSLA", "GLD", "GC", "XAUUSD"):
        return None

    analyzer = RegimeAnalyzer(confidence_threshold=min_confidence)
    state = analyzer.analyze(df)
    if state is None:
        return None

    regime = state["regime"]
    confidence = state["confidence"]
    z = state["z_score"]
    rsi = state["rsi"]
    regime_std = state["regime_std"]

    if confidence < min_confidence:
        return None

    close = df["close"].astype(float)
    price = current_price if current_price is not None else float(close.iloc[-1])
    sma20 = float(close.rolling(window=20, min_periods=20).mean().iloc[-1])
    sma50 = float(close.rolling(window=50, min_periods=50).mean().iloc[-1])

    # Deviation from the short-term moving average, normalised by the regime's
    # own volatility. This catches pullbacks to the 20 SMA even when price is
    # still above the longer-term regime mean (common in steady SPY uptrends).
    short_z = (price - sma20) / regime_std if regime_std > 0 else 0.0

    direction: Optional[str] = None
    if regime == "bull" and price > sma50 and (z <= -z_threshold or short_z <= -z_threshold):
        # Only go long if the pullback is still holding above the major trend.
        direction = "long"
    elif regime == "bear" and price < sma50 and (z >= z_threshold or short_z >= z_threshold):
        direction = "short"

    if direction is None:
        return None

    stop, target = _pullback_stop_target(df, direction, sma50)
    if stop is None or target is None:
        return None

    if direction == "long":
        if stop >= price or target <= price:
            return None
        risk = price - stop
        reward = target - price
    else:
        if stop <= price or target >= price:
            return None
        risk = stop - price
        reward = price - target

    if risk <= 0 or reward < risk * min_rr:
        return None

    # Confidence blends regime confidence and how stretched the pullback is.
    stretch_bonus = min(abs(z) / 3.0, 0.15)
    signal_confidence = round(min(confidence + stretch_bonus, 0.95), 2)

    return {
        "symbol": symbol,
        "source": "pullback_trend",
        "direction": direction,
        "confidence": signal_confidence,
        "current_price": price,
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "rsi": rsi,
        "regime": regime,
        "regime_confidence": confidence,
        "z_score": z,
        "short_z": round(short_z, 3),
        "stop": round(stop, 2),
        "target": round(target, 2),
    }


def regime_aware_mean_reversion_signal(
    symbol: str,
    df: pd.DataFrame,
    current_price: Optional[float] = None,
    min_confidence: float = 0.50,
    z_entry: float = 0.75,
) -> Optional[Dict[str, any]]:
    """
    Mean-reversion signal that trades deviations relative to the current regime.

    In a range regime we fade moves away from the regime mean.
    In bull/bear regimes we only fade *with* the prevailing trend
    (e.g. long when price falls back to the bull mean, short on a rally to the
    bear mean) — this avoids catching reversals against a strong trend.
    """
    analyzer = RegimeAnalyzer(confidence_threshold=min_confidence)
    state = analyzer.analyze(df)
    if state is None:
        return None

    regime = state["regime"]
    confidence = state["confidence"]
    z = state["z_score"]

    if confidence < min_confidence:
        return None

    close = df["close"].astype(float)
    price = current_price if current_price is not None else float(close.iloc[-1])
    atr = _compute_atr(df)
    current_atr = float(atr.iloc[-1]) if atr is not None else None
    if current_atr is None or current_atr <= 0:
        return None

    direction: Optional[str] = None
    if regime == "range":
        if z >= z_entry:
            direction = "short"
        elif z <= -z_entry:
            direction = "long"
    elif regime == "bull" and z <= -z_entry * 0.7:
        direction = "long"
    elif regime == "bear" and z >= z_entry * 0.7:
        direction = "short"

    if direction is None:
        return None

    regime_mean = state["regime_mean"]
    stop = regime_mean - (1.5 * current_atr) if direction == "long" else regime_mean + (1.5 * current_atr)
    target = regime_mean

    if direction == "long":
        if stop >= price or target <= price:
            return None
    else:
        if stop <= price or target >= price:
            return None

    risk = abs(price - stop)
    reward = abs(target - price)
    if risk <= 0 or reward < risk * 1.5:
        return None

    return {
        "symbol": symbol,
        "source": "mean_reversion",
        "direction": direction,
        "confidence": round(confidence, 2),
        "current_price": price,
        "regime": regime,
        "regime_confidence": confidence,
        "z_score": z,
        "stop": round(stop, 2),
        "target": round(target, 2),
    }


def _atr_percentile(df: pd.DataFrame, period: int = 14, lookback: int = 60) -> Optional[float]:
    """Return the percentile (0-1) of the current ATR vs the prior lookback window."""
    if len(df) < lookback + period:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    current = atr.iloc[-1]
    history = atr.dropna().iloc[-lookback:-1]
    if len(history) == 0 or pd.isna(current):
        return None
    return float((history <= current).sum() / len(history))


def regime_aware_breakout_signal(
    symbol: str,
    df: pd.DataFrame,
    current_price: Optional[float] = None,
    min_confidence: float = 0.65,
    max_atr_pct: float = 0.50,
    lookback: int = 5,
    min_rr: float = 2.0,
) -> Optional[Dict[str, any]]:
    """
    Volatility-contraction breakout signal.

    Only enters when the regime is strongly established and the tape is quiet
    (low ATR percentile). In a bull regime we buy a break above the recent
    consolidation high; in a bear regime we sell a break below the recent low.
    This complements the pullback signal by catching trend resumption after
    consolidation rather than after a dip.
    """
    if symbol not in ("SPY", "QQQ", "ES", "NQ", "TSLA", "GLD", "GC", "XAUUSD"):
        return None

    analyzer = RegimeAnalyzer(confidence_threshold=min_confidence)
    state = analyzer.analyze(df)
    if state is None or state["confidence"] < min_confidence:
        return None

    regime = state["regime"]
    confidence = state["confidence"]
    atr_pct = _atr_percentile(df)
    if atr_pct is None or atr_pct > max_atr_pct:
        return None

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    price = current_price if current_price is not None else float(close.iloc[-1])

    sma20 = float(close.rolling(window=20, min_periods=20).mean().iloc[-1])
    sma50 = float(close.rolling(window=50, min_periods=50).mean().iloc[-1])

    # Use the lookback days *before* the current bar for the breakout level.
    prior_high = float(high.tail(lookback + 1).iloc[:-1].max())
    prior_low = float(low.tail(lookback + 1).iloc[:-1].min())

    direction: Optional[str] = None
    if regime == "bull" and sma20 > sma50:
        if price > prior_high:
            direction = "long"
            stop = max(prior_low, sma20 * 0.995)
            target = price + (price - stop) * min_rr
    elif regime == "bear" and sma20 < sma50:
        if price < prior_low:
            direction = "short"
            stop = min(prior_high, sma20 * 1.005)
            target = price - (stop - price) * min_rr

    if direction is None:
        return None

    if direction == "long":
        if stop >= price or target <= price:
            return None
        risk = price - stop
        reward = target - price
    else:
        if stop <= price or target >= price:
            return None
        risk = stop - price
        reward = price - target

    if risk <= 0 or reward < risk * min_rr:
        return None

    return {
        "symbol": symbol,
        "source": "breakout",
        "direction": direction,
        "confidence": round(min(confidence + 0.05, 0.95), 2),
        "current_price": price,
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "regime": regime,
        "regime_confidence": confidence,
        "atr_pct": round(atr_pct, 3),
        "stop": round(stop, 2),
        "target": round(target, 2),
    }
