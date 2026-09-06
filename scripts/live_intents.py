#!/usr/bin/env python3
"""
Live signal → TradeIntent pipeline for the focus universe.

Fetches real market data (Massive + Yahoo), generates Massive-style and FMZ
quality signals, converts them into TradeIntents, sizes them, validates them
through the RiskGovernor, and optionally executes approved intents through the
UnifiedExecutionRouter.

Focus universe: SPY, QQQ, TSLA, GLD, ES, NQ, GC, XAUUSD,
plus OANDA forex: EURUSD, USDJPY, GBPUSD, AUDUSD.

Examples:
    # Dry-run: show signals + approved intents only
    MASSIVE_API_KEY=... python scripts/live_intents.py

    # Simulate broker execution without sending real orders
    MASSIVE_API_KEY=... python scripts/live_intents.py --simulate-execution

    # Live execution with interactive confirmation
    MASSIVE_API_KEY=... python scripts/live_intents.py --execute --account-value 50000

    # Live execution, auto-confirm each approved intent
    MASSIVE_API_KEY=... python scripts/live_intents.py --execute --yes
"""

import argparse
import asyncio
import json
import os
import sys
import warnings
from collections import defaultdict
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml
from loguru import logger

warnings.filterwarnings("ignore")

# Make the repo root importable when this script is run directly.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    import yfinance as yf
except ImportError as e:  # pragma: no cover
    raise SystemExit("yfinance is required: pip install yfinance") from e

# Alpha Trader imports
from agents.massive_analyst import MassiveAnalyst
from models import (
    ExecutionMode,
    TradeIntent,
    TradeStatus,
    generate_intent_id,
)
from models.decision_schemas import Direction
from strategies.fmz_parser import FMZParser
from strategies.fmz_runtime import (
    FMZRuntime,
    infer_fmz_exchange_name,
    is_quality_fmz_strategy,
)
from tools.risk_governor import RiskGovernor
from scripts.regime_overlay import (
    regime_aware_pullback_signal,
    regime_aware_mean_reversion_signal,
    regime_aware_breakout_signal,
)

# Keep log output readable; module-level loggers remain available but we only show
# warnings and errors on stderr.
logger.remove()
logger.add(sys.stderr, level="WARNING")


# ──────────────────────────────────────────────────────────────────────────────
# Focus universe & venue mapping
# ──────────────────────────────────────────────────────────────────────────────

FOCUS_SYMBOLS: Dict[str, str] = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "TSLA": "TSLA",
    "GLD": "GLD",
    "ES": "ES=F",
    "NQ": "NQ=F",
    "GC": "GC=F",
    "XAUUSD": "GC=F",  # Yahoo proxy; routed to OANDA as XAU/USD
    "EURUSD": "EURUSD=X",
    "USDJPY": "USDJPY=X",
    "GBPUSD": "GBPUSD=X",
    "AUDUSD": "AUDUSD=X",
}

# Symbols that Massive's free previous-close endpoint handles cleanly.
MASSIVE_EQUITY_SYMBOLS = {"SPY", "QQQ", "TSLA", "GLD"}

# Venue chosen for each symbol / asset class.
DEFAULT_VENUE_MAP: Dict[str, str] = {
    "SPY": "schwab",
    "QQQ": "schwab",
    "TSLA": "schwab",
    "GLD": "schwab",
    "ES": "topstep",
    "NQ": "topstep",
    "GC": "topstep",
    "XAUUSD": "oanda",
    "EURUSD": "oanda",
    "USDJPY": "oanda",
    "GBPUSD": "oanda",
    "AUDUSD": "oanda",
}

# Broker-native symbols for order entry.
VENUE_SYMBOL_MAP: Dict[str, Dict[str, str]] = {
    "topstep": {"ES": "ES", "NQ": "NQ", "GC": "GC"},
    "oanda": {
        "XAUUSD": "XAU/USD",
        "ES": "SPX500/USD",      # S&P 500 CFD
        "NQ": "NAS100/USD",      # Nasdaq-100 CFD
        "GC": "XAU/USD",         # gold spot
        "EURUSD": "EUR/USD",
        "USDJPY": "USD/JPY",
        "GBPUSD": "GBP/USD",
        "AUDUSD": "AUD/USD",
    },
}

# Futures contract point values (used for dollar-risk sizing).
FUTURES_POINT_VALUE: Dict[str, float] = {
    "ES": 12.50,
    "NQ": 20.0,
    "GC": 100.0,
}

# Tight, tradeable stop distances for intraday futures (points per contract).
# Targets are set at 2x the stop so the intent satisfies the 2:1 R:R minimum.
FUTURES_STOP_POINTS: Dict[str, float] = {
    "ES": 4.0,
    "NQ": 12.0,
    "GC": 2.0,
}

# Quality FMZ strategies we actually trust for live signals.
QUALITY_FMZ_IDENTIFIERS = [
    "fmz_strategy_4872",
    "fmz_btc_139b",
]


# ──────────────────────────────────────────────────────────────────────────────
# Config helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_config(path: str = "config/config.yaml") -> Dict[str, Any]:
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}; using defaults")
        return {}


def load_trading_params(path: str = "config/trading_params.yaml") -> Dict[str, Any]:
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}; using defaults")
        return {}


def log_paper_trade(
    intent: TradeIntent,
    decision: Any,
    log_path: str = "data/paper_trades.csv",
) -> None:
    """
    Append a signal/intent record to the paper-trade log.

    The log captures what the engine WOULD have traded, with exit_price and pnl
    left blank for manual or automated fill-in after the trade plays out.
    """
    import csv
    from pathlib import Path

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "timestamp",
        "symbol",
        "source",
        "direction",
        "entry",
        "stop",
        "target",
        "size",
        "conviction",
        "rr",
        "approved",
        "rejection_reason",
        "exit_price",
        "pnl",
        "notes",
    ]
    row = {
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": intent.symbol,
        "source": intent.thesis_id,
        "direction": intent.direction,
        "entry": round(intent.entry_price, 2),
        "stop": round(intent.stop_price, 2),
        "target": round(intent.target_price, 2),
        "size": intent.size,
        "conviction": intent.conviction,
        "rr": intent.risk_reward_ratio,
        "approved": decision.approved,
        "rejection_reason": decision.rejection_reason or "",
        "exit_price": "",
        "pnl": "",
        "notes": "",
    }
    try:
        write_header = not path.exists() or path.stat().st_size == 0
        with open(path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        logger.warning(f"Could not write paper-trade log: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Market data
# ──────────────────────────────────────────────────────────────────────────────

def fetch_yahoo_ohlcv(
    yahoo_ticker: str, period: str = "1mo", interval: str = "1d"
) -> Optional[pd.DataFrame]:
    """Download OHLCV from Yahoo Finance."""
    try:
        df = yf.download(
            yahoo_ticker,
            period=period,
            interval=interval,
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[0]).lower().replace("adj close", "adj_close") for c in df.columns]
        else:
            df.columns = [str(c).lower().replace("adj close", "adj_close") for c in df.columns]
        return df.dropna()
    except Exception as e:
        logger.warning(f"Yahoo fetch failed for {yahoo_ticker}: {e}")
        return None


def df_to_candles(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Convert Yahoo DataFrame to Massive-style candle dicts."""
    candles = []
    for _, row in df.iterrows():
        candles.append(
            {
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": int(row.get("volume", 0)),
            }
        )
    return candles


async def options_flow_aligned(symbol: str, direction: str, config: Dict[str, Any]) -> bool:
    """
    Confirm the intended direction with Unusual Whales options flow.

    Returns True if no API key is configured (disabled), or if flow data agrees
    with the trade direction. Currently checks net premium over the last hour.
    """
    try:
        from tools.unusual_whales import UnusualWhalesClient
    except Exception as e:
        logger.debug(f"Unusual Whales import failed: {e}")
        return True

    client = UnusualWhalesClient(config)
    if not client.enabled:
        return True

    try:
        flow = await client.options_flow(symbol)
        if not flow:
            return True
        # Sum net premium over the most recent flow records.
        records = flow if isinstance(flow, list) else flow.get("data", [])
        net_premium = 0.0
        for r in records[:20]:
            premium = float(r.get("premium", 0) or 0)
            side = (r.get("side") or "").lower()
            if side in ("call", "c"):
                net_premium += premium
            elif side in ("put", "p"):
                net_premium -= premium
        if direction == "long" and net_premium > 0:
            return True
        if direction == "short" and net_premium < 0:
            return True
        logger.info(f"Options flow disagrees with {direction} for {symbol}; skipping")
        return False
    except Exception as e:
        logger.warning(f"Options flow check failed for {symbol}: {e}")
        return True
    finally:
        await client.close()


def fetch_vix_daily(period: str = "3mo") -> Optional[pd.DataFrame]:
    """Fetch daily VIX closes from Yahoo Finance."""
    try:
        df = yf.download("^VIX", period=period, interval="1d", progress=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[0]).lower().replace("adj close", "adj_close") for c in df.columns]
        else:
            df.columns = [str(c).lower().replace("adj close", "adj_close") for c in df.columns]
        return df.dropna()
    except Exception as e:
        logger.debug(f"VIX history fetch failed: {e}")
    return None


def vix_info_for_date(vix_df: Optional[pd.DataFrame], target_date: Any) -> Optional[Dict[str, float]]:
    """Return VIX price and change % as of a historical date."""
    if vix_df is None or vix_df.empty:
        return None
    try:
        aligned = vix_df[vix_df.index <= target_date]
        if aligned.empty:
            return None
        price = float(aligned["close"].iloc[-1])
        prev_idx = max(0, len(aligned) - 2)
        prev_close = float(aligned["close"].iloc[prev_idx])
        return {
            "price": price,
            "previous_close": prev_close,
            "change_pct": (price / prev_close - 1.0) * 100.0 if prev_close else 0.0,
        }
    except Exception as e:
        logger.debug(f"VIX lookup for {target_date} failed: {e}")
    return None


def fetch_vix_info() -> Optional[Dict[str, float]]:
    """Return latest VIX price and change % from yfinance."""
    try:
        ticker = yf.Ticker("^VIX")
        info = ticker.info
        price = info.get("regularMarketPrice")
        prev_close = info.get("regularMarketPreviousClose")
        if price is not None and prev_close:
            return {
                "price": float(price),
                "previous_close": float(prev_close),
                "change_pct": (float(price) / float(prev_close) - 1.0) * 100.0,
            }
    except Exception as e:
        logger.debug(f"VIX fetch failed: {e}")
    return None


def vix_allows_long(vix_info: Optional[Dict[str, float]], max_vix: float = 25.0, max_change_pct: float = 15.0) -> bool:
    """
    Block long trades when VIX is elevated or spiking.
    Returns True if VIX data is missing to avoid blocking on data issues.
    """
    if vix_info is None:
        return True
    price = vix_info.get("price")
    change_pct = vix_info.get("change_pct")
    if price is not None and price > max_vix:
        return False
    if change_pct is not None and change_pct > max_change_pct:
        return False
    return True


def fetch_latest_gap_info(symbol: str) -> Optional[Dict[str, float]]:
    """
    Return the latest available price, previous close, and gap % for a symbol.

    Uses yfinance 1-minute pre/post-market history so the pipeline sees
    overnight / premarket moves instead of blindly using yesterday's close.
    """
    try:
        ticker = yf.Ticker(symbol)
        intraday = ticker.history(prepost=True, period="1d", interval="1m")
        daily = ticker.history(period="5d", interval="1d")
        if intraday.empty or daily.empty or len(daily) < 2:
            return None
        latest_price = float(intraday["Close"].iloc[-1])
        prev_close = float(daily["Close"].iloc[-2])
        if prev_close <= 0:
            return None
        gap_pct = (latest_price / prev_close - 1.0) * 100.0
        return {
            "price": latest_price,
            "previous_close": prev_close,
            "gap_pct": gap_pct,
        }
    except Exception as e:
        logger.debug(f"Gap fetch failed for {symbol}: {e}")
    return None


def gap_aligns(direction: str, gap_pct: Optional[float], threshold: float = 0.5) -> bool:
    """
    Skip an intent if the latest price is gapping sharply against the intended direction.
    Threshold is in percent points (e.g. 0.5 = 0.5%).
    """
    if gap_pct is None:
        return False  # fail closed
    if direction == "long" and gap_pct < -threshold:
        return False
    if direction == "short" and gap_pct > threshold:
        return False
    return True


def compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Return the latest Average True Range from a Yahoo-style OHLCV df."""
    if len(df) < period + 1:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean().iloc[-1]
    return float(atr) if pd.notna(atr) else None


def atr_percentile(df: pd.DataFrame, period: int = 14, lookback: int = 60) -> Optional[float]:
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


def volatility_not_extreme(
    df: pd.DataFrame,
    low_pct: float = 0.20,
    high_pct: float = 0.80,
) -> bool:
    """Return True unless 14-day ATR is in the lowest or highest 20% of the lookback."""
    pct = atr_percentile(df)
    if pct is None:
        return True
    return low_pct <= pct <= high_pct


def compute_rsi(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Return the latest Relative Strength Index (0-100)."""
    if len(df) < period + 1:
        return None
    close = df["close"].astype(float)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean().iloc[-1]
    avg_loss = loss.rolling(window=period, min_periods=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[Dict[str, float]]:
    """Return the latest MACD line, signal line, and histogram."""
    if len(df) < slow + signal:
        return None
    close = df["close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
    }


def compute_bollinger_position(
    df: pd.DataFrame,
    period: int = 20,
    std: float = 2.0,
) -> Optional[float]:
    """Return the position of the latest close within the Bollinger Bands (0=lower, 1=upper)."""
    if len(df) < period:
        return None
    close = df["close"].astype(float)
    sma = close.rolling(window=period, min_periods=period).mean()
    stddev = close.rolling(window=period, min_periods=period).std()
    upper = sma + std * stddev
    lower = sma - std * stddev
    width = upper.iloc[-1] - lower.iloc[-1]
    if width <= 0:
        return 0.5
    return float((close.iloc[-1] - lower.iloc[-1]) / width)


def compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Return the latest Average Directional Index (0-100).

    ADX measures trend strength independent of direction.  Values above 25
    indicate a trending market; below 20 indicates a weak/ranging market.
    """
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
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()
    return float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else None


def regime_trending(df: pd.DataFrame, threshold: float = 25.0) -> bool:
    """Return True if the market is trending (ADX above threshold)."""
    adx = compute_adx(df)
    if adx is None:
        return True  # don't block on missing data
    return adx >= threshold


def regime_ranging(df: pd.DataFrame, threshold: float = 20.0) -> bool:
    """Return True if the market is ranging/weak-trend (ADX below threshold)."""
    adx = compute_adx(df)
    if adx is None:
        return False
    return adx <= threshold


def volume_confirmed(df: pd.DataFrame, lookback: int = 20, min_multiple: float = 0.5) -> bool:
    """Return False only if the latest volume is unusually thin (< 50% of average)."""
    if len(df) < lookback + 1:
        return True
    volumes = df["volume"].astype(float)
    avg_volume = volumes.iloc[-lookback - 1 : -1].mean()
    latest_volume = volumes.iloc[-1]
    if avg_volume <= 0:
        return True
    return float(latest_volume) >= avg_volume * min_multiple


def momentum_aligned(df: pd.DataFrame, direction: str) -> bool:
    """
    Avoid only extreme overbought/oversold conditions.
    Healthy pullbacks within a trend are allowed.
    """
    rsi = compute_rsi(df)
    bb_pos = compute_bollinger_position(df)

    if direction == "long":
        if rsi is not None and rsi > 85:
            return False
        if bb_pos is not None and bb_pos > 0.98:
            return False
    elif direction == "short":
        if rsi is not None and rsi < 15:
            return False
        if bb_pos is not None and bb_pos < 0.02:
            return False
    return True


def has_bullish_rejection(df: pd.DataFrame) -> bool:
    """Return True if the last candle has a lower wick larger than its body."""
    if len(df) < 1:
        return False
    row = df.iloc[-1]
    open_p = float(row.get("open", 0))
    high = float(row.get("high", 0))
    low = float(row.get("low", 0))
    close = float(row.get("close", 0))
    body = abs(close - open_p)
    lower_wick = min(open_p, close) - low
    return lower_wick > body * 1.0 and close > open_p


def has_bearish_rejection(df: pd.DataFrame) -> bool:
    """Return True if the last candle has an upper wick larger than its body."""
    if len(df) < 1:
        return False
    row = df.iloc[-1]
    open_p = float(row.get("open", 0))
    high = float(row.get("high", 0))
    low = float(row.get("low", 0))
    close = float(row.get("close", 0))
    body = abs(close - open_p)
    upper_wick = high - max(open_p, close)
    return upper_wick > body * 1.0 and close < open_p


def _slice_hourly(
    hourly_df: Optional[pd.DataFrame],
    target_date: Optional[Any] = None,
) -> Optional[pd.DataFrame]:
    """Return hourly data up to the end of the target trading day."""
    if hourly_df is None or hourly_df.empty:
        return None
    df = hourly_df.copy()
    if target_date is not None:
        target_ts = pd.Timestamp(target_date)
        if df.index.tz is not None and target_ts.tzinfo is None:
            target_ts = target_ts.tz_localize(df.index.tz)
        target_ts = target_ts + pd.Timedelta(days=1)
        df = df[df.index <= target_ts]
    return df if not df.empty else None


def mean_reversion_quality_score(
    symbol: str,
    direction: str,
    daily_df: pd.DataFrame,
    hourly_df: Optional[pd.DataFrame],
    vix_info: Optional[Dict[str, float]],
    target_date: Optional[Any] = None,
) -> int:
    """
    Score a mean-reversion setup from 0 to 5.
    Higher score = higher probability pullback-to-mean trade.
    """
    score = 0
    rsi = compute_rsi(daily_df)
    bb_pos = compute_bollinger_position(daily_df)
    hourly = _slice_hourly(hourly_df, target_date)
    hourly_rsi = compute_rsi(hourly) if hourly is not None and len(hourly) >= 15 else None
    hourly_macd = compute_macd(hourly) if hourly is not None and len(hourly) >= 35 else None

    if direction == "long":
        if bb_pos is not None and bb_pos <= 0.15:
            score += 1
        elif bb_pos is not None and bb_pos <= 0.25:
            score += 0
        if rsi is not None and rsi <= 32:
            score += 1
        if hourly_rsi is not None and hourly_rsi <= 35:
            score += 1
        if hourly_macd is not None and hourly_macd["histogram"] >= 0:
            # Hourly MACD histogram positive or flat — short-term momentum turning.
            score += 1
        if has_bullish_rejection(daily_df):
            score += 1
        if vix_allows_long(vix_info):
            score += 1
    elif direction == "short":
        if bb_pos is not None and bb_pos >= 0.85:
            score += 1
        elif bb_pos is not None and bb_pos >= 0.75:
            score += 0
        if rsi is not None and rsi >= 68:
            score += 1
        if hourly_rsi is not None and hourly_rsi >= 65:
            score += 1
        if hourly_macd is not None and hourly_macd["histogram"] < 0:
            score += 1
        if has_bearish_rejection(daily_df):
            score += 1
        if vix_info is not None and vix_info.get("price", 0) < 20:
            score += 1

    return int(score)


def trend_aligned(df: pd.DataFrame, direction: str, period: int = 20) -> bool:
    """Return True if price is aligned with the symbol's own trend SMA."""
    if len(df) < period:
        return True  # Not enough history — allow signal.
    close = df["close"].astype(float)
    sma = close.rolling(window=period, min_periods=period).mean().iloc[-1]
    price = close.iloc[-1]
    if direction == "long":
        return float(price) >= float(sma)
    if direction == "short":
        return float(price) <= float(sma)
    return True


def spy_regime_aligned(
    symbol: str,
    direction: str,
    spy_df: Optional[pd.DataFrame],
) -> bool:
    """For US equity indices, require the trade direction to match SPY's 20-day trend."""
    if symbol not in ("SPY", "QQQ", "ES", "NQ"):
        return True
    if spy_df is None or len(spy_df) < 20:
        return True
    close = spy_df["close"].astype(float)
    sma20 = close.rolling(window=20, min_periods=20).mean().iloc[-1]
    price = close.iloc[-1]
    if direction == "long":
        return float(price) >= float(sma20)
    if direction == "short":
        return float(price) <= float(sma20)
    return True


def fetch_hourly_ohlcv(yahoo_ticker: str) -> Optional[pd.DataFrame]:
    """Fetch hourly OHLCV from Yahoo Finance (last ~730 days)."""
    try:
        df = yf.download(
            yahoo_ticker,
            period="1mo",
            interval="1h",
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[0]).lower().replace("adj close", "adj_close") for c in df.columns]
        else:
            df.columns = [str(c).lower().replace("adj close", "adj_close") for c in df.columns]
        return df.dropna()
    except Exception as e:
        logger.warning(f"Hourly Yahoo fetch failed for {yahoo_ticker}: {e}")
        return None


def hourly_trend_aligned(
    hourly_df: pd.DataFrame,
    direction: str,
    short_period: int = 20,
    long_period: int = 50,
    target_date: Optional[Any] = None,
) -> bool:
    """
    Require the hourly trend structure to agree with the intended direction.
    Price can pull back to the short SMA as long as the short SMA stays above
    the long SMA (uptrend structure). This avoids blocking healthy retracements.
    For backtests, pass target_date to only consider bars up to that timestamp.
    """
    if hourly_df is None or hourly_df.empty:
        return True
    df = hourly_df.copy()
    if target_date is not None:
        target_ts = pd.Timestamp(target_date)
        if df.index.tz is not None and target_ts.tzinfo is None:
            target_ts = target_ts.tz_localize(df.index.tz)
        # Include the full target trading day (close is ~16:00 that day).
        target_ts = target_ts + pd.Timedelta(days=1)
        df = df[df.index <= target_ts]
    if len(df) < long_period:
        return True
    close = df["close"].astype(float)
    sma_short = close.rolling(window=short_period, min_periods=short_period).mean().iloc[-1]
    sma_long = close.rolling(window=long_period, min_periods=long_period).mean().iloc[-1]
    price = close.iloc[-1]
    if direction == "long":
        return float(price) >= float(sma_short) or float(sma_short) >= float(sma_long)
    if direction == "short":
        return float(price) <= float(sma_short) or float(sma_short) <= float(sma_long)
    return True


def strong_trend_aligned(
    df: pd.DataFrame,
    direction: str,
    short_period: int = 20,
    long_period: int = 50,
) -> bool:
    """
    Require price to be aligned with both short- and long-term SMAs.
    Filters out choppy, whipsaw-prone regimes where only the fast SMA is touched.
    """
    if len(df) < long_period:
        return True
    close = df["close"].astype(float)
    sma_short = close.rolling(window=short_period, min_periods=short_period).mean().iloc[-1]
    sma_long = close.rolling(window=long_period, min_periods=long_period).mean().iloc[-1]
    price = close.iloc[-1]
    if direction == "long":
        return float(price) >= float(sma_short) and float(sma_short) >= float(sma_long)
    if direction == "short":
        return float(price) <= float(sma_short) and float(sma_short) <= float(sma_long)
    return True


async def fetch_topstep_price(symbol: str) -> Optional[float]:
    """Fetch a live futures price from TopstepX when credentials are configured."""
    from tools.topstep import get_topstep_client

    client = get_topstep_client()
    try:
        price = await client.get_price(symbol)
        last = price.get("last")
        if last:
            return round(float(last), 2)
    except Exception as e:
        logger.warning(f"Topstep price fetch failed for {symbol}: {e}")
    return None


async def fetch_oanda_price(instrument: str = "XAU/USD") -> Optional[float]:
    """Fetch a live mid price from OANDA when credentials are configured."""
    from tools.oanda import get_oanda_client

    client = get_oanda_client()
    if not client.client:
        return None
    try:
        quote = await client.get_price(instrument.replace("_", "/"))
        bid = quote.get("bid")
        ask = quote.get("ask")
        if bid and ask:
            return round((float(bid) + float(ask)) / 2.0, 2)
    except Exception as e:
        logger.warning(f"OANDA price fetch failed for {instrument}: {e}")
    return None


async def fetch_portfolio_state(
    portfolio_risk_pct: float = 0.5,
) -> Dict[str, Any]:
    """
    Build a live portfolio snapshot from configured brokers.

    Combines Schwab (equities/options) and OANDA (forex/CFDs) account data.
    If a broker is not connected or its token is invalid, it is skipped with a
    warning.  Open risk is estimated as 2% of open position notional value.
    """
    state: Dict[str, Any] = {
        "account_value": 0.0,
        "buying_power": 0.0,
        "day_pnl": 0.0,
        "open_risk": 0.0,
        "consecutive_losses": 0,
        "sources": [],
    }

    # Schwab
    try:
        from tools.schwab import get_schwab_client
        schwab = get_schwab_client()
        if schwab.client:
            account = await schwab.get_account()
            if "error" not in account:
                securities = account.get("securitiesAccount", {})
                current = securities.get("currentBalances", {})
                projected = securities.get("projectedBalances", {})
                equity = current.get("liquidationValue") or projected.get("buyingPower", 0)
                bp = projected.get("buyingPower", 0) or equity
                day_pnl = current.get("currentDayProfitLoss", 0)
                state["account_value"] += float(equity or 0)
                state["buying_power"] += float(bp or 0)
                state["day_pnl"] += float(day_pnl or 0)
                state["sources"].append("schwab")

                positions = await schwab.get_positions()
                for pos in positions:
                    mv = float(pos.get("market_value", 0))
                    state["open_risk"] += abs(mv) * (portfolio_risk_pct / 100.0)
    except Exception as e:
        logger.warning(f"Live portfolio sync failed for Schwab: {e}")

    # OANDA
    try:
        from tools.oanda import get_oanda_client
        oanda = get_oanda_client()
        if oanda.client:
            account = await oanda.get_account()
            balance = float(account.get("balance", 0))
            unrealized = float(account.get("unrealizedPL", 0))
            state["account_value"] += balance + max(unrealized, 0)
            state["buying_power"] += balance + max(unrealized, 0)
            state["sources"].append("oanda")

            positions = await oanda.get_positions()
            for pos in positions:
                # 1 unit ≈ $1 at risk per $1 price move; estimate risk as 1% of notional.
                notional = float(pos.get("size", 0)) * float(pos.get("entry", 0))
                state["open_risk"] += abs(notional) * 0.01
    except Exception as e:
        logger.warning(f"Live portfolio sync failed for OANDA: {e}")

    # Consecutive losses from circuit-breaker state
    try:
        from tools.circuit_breakers import _load_state
        cb_state = _load_state()
        state["consecutive_losses"] = int(cb_state.get("consecutive_losses", 0))
    except Exception:
        pass

    return state


async def fetch_massive_prev_closes(symbols: List[str], api_key: str) -> Dict[str, float]:
    """Query Massive's previous-close endpoint for equity symbols."""
    from market_data.providers.massive_provider import MassiveProvider

    config = {"market_data_apis": {"massive": {"enabled": True, "api_key": api_key}}}
    provider = MassiveProvider(config)
    prices: Dict[str, float] = {}
    candidates = [s for s in symbols if s in MASSIVE_EQUITY_SYMBOLS]
    try:
        for i, sym in enumerate(candidates):
            try:
                data = await provider.get_previous_close(sym)
                result = (data or {}).get("results", [{}])[0]
                close = result.get("c")
                if close is not None:
                    prices[sym] = float(close)
            except Exception as e:
                logger.warning(f"Massive previous-close failed for {sym}: {e}")
            if i < len(candidates) - 1:
                await asyncio.sleep(13)  # free-tier 5 req/min
    finally:
        await provider.close()
    return prices


# ──────────────────────────────────────────────────────────────────────────────
# Signal generation
# ──────────────────────────────────────────────────────────────────────────────

def massive_style_signal(
    symbol: str, candles: List[Dict[str, Any]], current_price: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """Run MassiveAnalyst price-action logic on Yahoo candles."""
    if len(candles) < 2:
        return None
    current = current_price if current_price is not None else candles[-1]["close"]
    direction, confidence, key_points, risks = MassiveAnalyst._evaluate(
        None, candles, None, current
    )
    return {
        "symbol": symbol,
        "source": "massive-style",
        "direction": direction.value if hasattr(direction, "value") else str(direction).lower(),
        "confidence": confidence,
        "current_price": current,
        "key_points": key_points,
        "risks": risks,
    }


def fmz_signals_for_symbol(symbol: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Run quality FMZ strategies on real OHLCV."""
    parser = FMZParser()
    catalog = parser.load_catalog()
    lookup = {e.python_identifier: e for e in catalog}

    signals = []
    for ident in QUALITY_FMZ_IDENTIFIERS:
        entry = lookup.get(ident)
        if not entry or not is_quality_fmz_strategy(entry.source_code, entry.description):
            continue
        args = {a["argument"]: a["default"] for a in entry.arguments}
        runtime = FMZRuntime(
            source_code=entry.source_code,
            language=entry.source_language,
            strategy_name=ident,
            args=args,
        )
        batch = runtime.run(
            symbol=symbol,
            ohlcv_df=df,
            tick_limit=2,
            exchange_name=infer_fmz_exchange_name(symbol),
            max_signals=1,
            quality_only=True,
        )
        for sig in batch:
            signals.append(
                {
                    "strategy": ident,
                    "direction": sig.direction,
                    "entry": round(sig.entry_price, 2),
                    "stop": round(sig.stop_price, 2),
                    "target": round(sig.target_price, 2),
                    "conviction": sig.conviction,
                }
            )
    return signals


def mean_reversion_signal(
    symbol: str,
    df: pd.DataFrame,
    current_price: Optional[float] = None,
    hourly_df: Optional[pd.DataFrame] = None,
    vix_info: Optional[Dict[str, float]] = None,
    target_date: Optional[Any] = None,
    min_quality_score: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Regime-aware mean-reversion signal.

    Replaces the fixed Bollinger + RSI thresholds with a deviation measured
    relative to the current regime's equilibrium (item #4). In a ranging regime
    the signal fades moves away from the regime mean; in bull/bear regimes it
    only fades pullbacks back toward the prevailing trend, avoiding reversals
    against strong trends.
    """
    sig = regime_aware_mean_reversion_signal(symbol, df, current_price=current_price)
    if sig is None:
        return None

    # Backward-compatible keys for the intent builder / logs.
    sig["bb_position"] = round(
        0.5 - sig["z_score"] * 0.15, 2
    )  # rough mapping from z to band position
    sig["quality_score"] = 3
    return sig


def pullback_trend_signal(
    symbol: str,
    df: pd.DataFrame,
    current_price: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Regime-aware pullback-to-trend signal for indices and high-beta equities.

    Replaces the fixed 20/50-SMA + RSI<40 rule with a dynamic regime overlay:
      - Detect bull / bear / range regime and its confidence.
      - Only trade when the regime confidence is high (item #3).
      - Enter on a pullback/rally measured as a z-score inside the current
        regime's mean and volatility (items #2 and #4).
      - Long pullbacks in bull regimes, short rallies in bear regimes; no signal
        in uncertain/range regimes.
    """
    return regime_aware_pullback_signal(symbol, df, current_price=current_price)


def breakout_signal(
    symbol: str,
    df: pd.DataFrame,
    current_price: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Regime-aware volatility-contraction breakout signal.

    Trades a quiet consolidation breakout in the direction of an established
    regime. This is the second custom source designed to raise trade frequency
    while keeping expectancy positive.
    """
    return regime_aware_breakout_signal(symbol, df, current_price=current_price)


# ──────────────────────────────────────────────────────────────────────────────
# Intent construction
# ──────────────────────────────────────────────────────────────────────────────

def build_pullback_trend_intent(
    symbol: str,
    signal: Dict[str, Any],
    df: pd.DataFrame,
    venue: str,
    params: Dict[str, Any],
) -> Optional[TradeIntent]:
    """Convert a regime-aware pullback-to-trend signal into a sized TradeIntent."""
    direction = signal["direction"]
    if direction not in ("long", "short"):
        return None

    canonical = symbol
    symbol = VENUE_SYMBOL_MAP.get(venue, {}).get(symbol, symbol)
    entry = float(signal["current_price"])
    stop = float(signal["stop"])
    target = float(signal.get("target", entry + (entry - stop) * 2.0))

    return TradeIntent(
        id=generate_intent_id(),
        capsule_id="live_signals",
        thesis_id="pullback_trend",
        symbol=symbol,
        direction=direction,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        conviction=round(signal["confidence"], 2),
        invalidation_price=round(stop, 2),
        time_stop=datetime.utcnow() + timedelta(days=5),
        risk_reward_ratio=round(abs((target - entry) / (entry - stop)), 2),
        size=None,
        execution_mode=ExecutionMode.CONFIRM,
        venue=venue,
        evidence_citations=[
            f"regime={signal.get('regime')} conf={signal.get('regime_confidence')} z={signal.get('z_score')} | "
            f"20SMA {signal.get('sma20')} | 50SMA {signal.get('sma50')} | RSI {signal.get('rsi')}"
        ],
        tags=["pullback_trend", "live", f"regime:{signal.get('regime')}"],
    )


def build_breakout_intent(
    symbol: str,
    signal: Dict[str, Any],
    df: pd.DataFrame,
    venue: str,
    params: Dict[str, Any],
) -> Optional[TradeIntent]:
    """Convert a regime-aware breakout signal into a sized TradeIntent."""
    direction = signal["direction"]
    if direction not in ("long", "short"):
        return None

    symbol = VENUE_SYMBOL_MAP.get(venue, {}).get(symbol, symbol)
    entry = float(signal["current_price"])
    stop = float(signal["stop"])
    target = float(signal.get("target", entry + (entry - stop) * 2.0))

    return TradeIntent(
        id=generate_intent_id(),
        capsule_id="live_signals",
        thesis_id="breakout",
        symbol=symbol,
        direction=direction,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        conviction=round(signal["confidence"], 2),
        invalidation_price=round(stop, 2),
        time_stop=datetime.utcnow() + timedelta(days=5),
        risk_reward_ratio=round(abs((target - entry) / (entry - stop)), 2),
        size=None,
        execution_mode=ExecutionMode.CONFIRM,
        venue=venue,
        evidence_citations=[
            f"regime={signal.get('regime')} conf={signal.get('regime_confidence')} atr_pct={signal.get('atr_pct')} | "
            f"20SMA {signal.get('sma20')} | 50SMA {signal.get('sma50')}"
        ],
        tags=["breakout", "live", f"regime:{signal.get('regime')}"],
    )


def build_massive_intent(
    symbol: str,
    signal: Dict[str, Any],
    df: pd.DataFrame,
    venue: str,
    params: Dict[str, Any],
) -> Optional[TradeIntent]:
    """Convert a Massive-style directional signal into a sized TradeIntent."""
    direction = signal["direction"]
    if direction == "neutral":
        return None

    # Map to broker-native symbol where needed (e.g. XAUUSD -> XAU/USD).
    symbol = VENUE_SYMBOL_MAP.get(venue, {}).get(symbol, symbol)

    entry = float(signal["current_price"])

    # Futures use tight, contract-specific point stops so position sizing is viable.
    canonical = next(
        (s for s in FUTURES_STOP_POINTS if symbol.upper().startswith(s)),
        None,
    )
    if venue == "topstep" and canonical:
        stop_points = FUTURES_STOP_POINTS[canonical]
        target_points = stop_points * 2.0
        if direction == "long":
            stop = entry - stop_points
            target = entry + target_points
        else:
            stop = entry + stop_points
            target = entry - target_points
    else:
        atr = compute_atr(df, period=14)
        if not atr or atr <= 0:
            logger.warning(f"Cannot compute ATR for {symbol}; skipping Massive-style intent")
            return None
        stop_dist = 1.5 * atr
        target_dist = 3.0 * atr  # 1:2 risk/reward

        # Cap stop distance at 1.5% of entry so that integer-unit sizing stays
        # within the default 0.5% account-risk limit regardless of ATR expansion.
        max_stop_pct = 0.015
        max_stop_dist = entry * max_stop_pct
        if stop_dist > max_stop_dist:
            stop_dist = max_stop_dist
            target_dist = stop_dist * 2.0

        if direction == "long":
            stop = entry - stop_dist
            target = entry + target_dist
        else:
            stop = entry + stop_dist
            target = entry - target_dist

    return TradeIntent(
        id=generate_intent_id(),
        capsule_id="live_signals",
        thesis_id="massive_style",
        symbol=symbol,
        direction=direction,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        conviction=round(signal["confidence"], 2),
        invalidation_price=round(stop, 2),
        time_stop=datetime.utcnow() + timedelta(days=5),
        risk_reward_ratio=round(abs((target - entry) / (entry - stop)), 2),
        size=None,  # sized later
        execution_mode=ExecutionMode.CONFIRM,
        venue=venue,
        evidence_citations=signal.get("key_points", []) + signal.get("risks", []),
        tags=["massive_style", "live"],
    )


def cap_stop_distance(
    entry: float,
    stop: float,
    max_pct: float = 0.015,
) -> float:
    """
    Cap the stop distance as a percentage of entry price.

    Prevents any single setup from producing a stop so wide that it blows
    through the account-risk limit regardless of signal quality.
    """
    max_dist = entry * max_pct
    if stop < entry:
        return max(stop, entry - max_dist)
    return min(stop, entry + max_dist)


def build_mean_reversion_intent(
    symbol: str,
    signal: Dict[str, Any],
    df: pd.DataFrame,
    venue: str,
    params: Dict[str, Any],
) -> Optional[TradeIntent]:
    """
    Convert a regime-aware mean-reversion signal into a TradeIntent.

    If the signal already provides stop/target (from the regime overlay), use
    those. Otherwise fall back to Bollinger-based levels for legacy callers.
    A hard %-of-entry cap prevents oversized stops.
    """
    direction = signal["direction"]
    if direction == "neutral":
        return None

    canonical = symbol
    symbol = VENUE_SYMBOL_MAP.get(venue, {}).get(symbol, symbol)
    entry = float(signal["current_price"])

    # Regime-aware signals supply explicit stop/target relative to the regime mean.
    if "stop" in signal and "target" in signal:
        stop = float(signal["stop"])
        target = float(signal["target"])
    else:
        close = df["close"].astype(float)
        sma20 = close.rolling(window=20, min_periods=20).mean().iloc[-1]
        std20 = close.rolling(window=20, min_periods=20).std().iloc[-1]
        upper = float(sma20 + 2 * std20)
        lower = float(sma20 - 2 * std20)
        atr = compute_atr(df, period=14)
        if direction == "long":
            stop = min(lower * 0.995, entry - (atr * 0.75)) if atr else lower * 0.995
            target = upper
        else:
            stop = max(upper * 1.005, entry + (atr * 0.75)) if atr else upper * 1.005
            target = lower

    # Hard cap: stop can never be more than 1.5% away from entry.
    stop = cap_stop_distance(entry, stop, max_pct=0.015)

    if stop == entry:
        return None

    # Ensure target still provides at least 2:1 R:R after capping.
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if reward < risk * 2.0:
        target = entry + (risk * 2.0) if direction == "long" else entry - (risk * 2.0)

    return TradeIntent(
        id=generate_intent_id(),
        capsule_id="live_signals",
        thesis_id="mean_reversion",
        symbol=symbol,
        direction=direction,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        conviction=round(signal["confidence"], 2),
        invalidation_price=round(stop, 2),
        time_stop=datetime.utcnow() + timedelta(days=3),
        risk_reward_ratio=round(abs((target - entry) / (entry - stop)), 2),
        size=None,
        execution_mode=ExecutionMode.CONFIRM,
        venue=venue,
        evidence_citations=[
            f"regime={signal.get('regime')} z={signal.get('z_score')} | RSI {signal.get('rsi')}"
        ],
        tags=["mean_reversion", "live", f"mr_quality:{signal.get('quality_score', 0)}"],
    )


def build_fmz_intent(
    symbol: str,
    signal: Dict[str, Any],
    venue: str,
) -> TradeIntent:
    """Convert an FMZ quality signal into a TradeIntent."""
    direction = signal["direction"]
    # Map to broker-native symbol where needed.
    symbol = VENUE_SYMBOL_MAP.get(venue, {}).get(symbol, symbol)
    entry = float(signal["entry"])

    # Override wide FMZ stops with tight, executable futures stops.
    canonical = next(
        (s for s in FUTURES_STOP_POINTS if symbol.upper().startswith(s)),
        None,
    )
    if venue == "topstep" and canonical:
        stop_points = FUTURES_STOP_POINTS[canonical]
        target_points = stop_points * 2.0
        if direction == "long":
            stop = entry - stop_points
            target = entry + target_points
        else:
            stop = entry + stop_points
            target = entry - target_points
    else:
        stop = float(signal["stop"])
        target = float(signal["target"])

    return TradeIntent(
        id=generate_intent_id(),
        capsule_id="live_signals",
        thesis_id=signal["strategy"],
        symbol=symbol,
        direction=direction,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        conviction=round(signal["conviction"], 2),
        invalidation_price=round(stop, 2),
        time_stop=datetime.utcnow() + timedelta(days=5),
        risk_reward_ratio=round(abs((target - entry) / (entry - stop)), 2),
        size=None,
        execution_mode=ExecutionMode.CONFIRM,
        venue=venue,
        evidence_citations=[f"fmz:{signal['strategy']}"],
        tags=["fmz", signal["strategy"], "live"],
    )


def confirmed_intents(
    massive_intents: List[TradeIntent],
    fmz_intents: List[TradeIntent],
) -> List[TradeIntent]:
    """
    Return the set of intents to trade.

    FMZ quality signals can stand alone. Massive-style signals are only kept
    when they agree with an FMZ signal on direction for the same symbol; this
    prevents the noisier Massive-only calls from diluting the track record.
    When both sources survive, FMZ intents are preferred.
    """
    if not fmz_intents and not massive_intents:
        return []
    if not fmz_intents:
        return []
    fmz_dirs = {i.direction for i in fmz_intents}
    confirmed_massive = [m for m in massive_intents if m.direction in fmz_dirs]
    # Prefer FMZ's explicit strategy signals when both sources agree.
    return fmz_intents if fmz_intents else confirmed_massive


async def build_option_intent(
    underlying: str,
    signal: Dict[str, Any],
    params: Dict[str, Any],
) -> Optional[TradeIntent]:
    """Build a Schwab option intent from an underlying signal (long call / long put)."""
    try:
        from tools.schwab import schwab_get_option_chain_parsed
    except Exception as e:
        logger.warning(f"Option chain unavailable: {e}")
        return None

    direction = signal["direction"]
    if direction == "neutral":
        return None

    opt_cfg = params.get("options", {})
    min_dte = int(opt_cfg.get("min_dte", 14))
    target_expiration = (datetime.utcnow() + timedelta(days=min_dte)).strftime("%Y-%m-%d")

    chain = await schwab_get_option_chain_parsed(
        underlying,
        direction="long" if direction == "long" else "short",
        expiration=target_expiration,
    )
    if not chain or "error" in chain or not chain.get("strikes"):
        logger.warning(f"No option chain for {underlying}: {chain}")
        return None

    option_type = chain.get("option_type", "call")
    expiration = chain.get("expiration")
    strikes = chain["strikes"]

    # Pick a strike with delta inside the configured sweet spot if possible.
    opt_cfg = params.get("options", {})
    delta_min = opt_cfg.get("delta_min", 0.50)
    delta_max = opt_cfg.get("delta_max", 0.70)
    candidate = None
    for s in strikes:
        delta = abs(float(s.get("delta", 0)))
        if delta_min <= delta <= delta_max:
            candidate = s
            break
    if candidate is None:
        candidate = strikes[len(strikes) // 2]

    strike = float(candidate["strike"])
    premium = float(candidate.get("ask") or candidate.get("last") or candidate.get("bid"))
    if premium <= 0:
        logger.warning(f"Invalid option premium for {underlying}: {premium}")
        return None

    # Per-contract dollar values for risk math (1 contract = 100 shares).
    contract_premium = premium * 100.0

    max_cost = opt_cfg.get("max_position_cost", 500)
    if contract_premium > max_cost:
        logger.warning(
            f"{underlying} {option_type} @{strike} premium ${contract_premium:.2f} "
            f"exceeds max_position_cost ${max_cost}; skipping option intent"
        )
        return None

    stop = contract_premium * 0.80  # 20% premium stop
    target = contract_premium * 1.50  # 50% gain target
    rr = round(abs((target - contract_premium) / (contract_premium - stop)), 2)

    max_qty = opt_cfg.get("max_quantity", 2)
    contracts = max(1, int(max_cost // contract_premium))
    contracts = min(contracts, max_qty)

    # Build OCC-style option symbol: "SPY   250620C00450000"
    exp_dt = datetime.strptime(expiration, "%Y-%m-%d")
    exp_str = exp_dt.strftime("%y%m%d")
    opt_letter = "C" if option_type == "call" else "P"
    occ_symbol = f"{underlying:<6}{exp_str}{opt_letter}{int(strike * 1000):08d}"
    dte = max(1, (exp_dt - datetime.utcnow()).days)
    if dte < min_dte:
        logger.warning(
            f"{underlying} {option_type} expiration {expiration} is only {dte} DTE; "
            f"minimum required is {min_dte} DTE; skipping option intent"
        )
        return None

    return TradeIntent(
        id=generate_intent_id(),
        capsule_id="live_signals",
        thesis_id=f"option_{underlying}",
        symbol=occ_symbol,
        direction=direction,
        entry_price=round(contract_premium, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        conviction=round(signal["confidence"], 2),
        invalidation_price=round(stop, 2),
        time_stop=datetime.utcnow() + timedelta(days=dte),
        risk_reward_ratio=rr,
        size=contracts,
        execution_mode=ExecutionMode.CONFIRM,
        venue="schwab",
        evidence_citations=[f"{underlying} {option_type} @{strike} exp {expiration}"],
        tags=["option", underlying, option_type, "live"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Sizing
# ──────────────────────────────────────────────────────────────────────────────

def get_contract_multiplier(intent: TradeIntent, params: Dict[str, Any]) -> float:
    """Return the dollar-risk multiplier for one unit of the intent."""
    # Options store per-contract dollar values, so no extra multiplier is needed.
    if "option" in intent.tags:
        return 1.0
    if intent.venue == "topstep":
        canonical = None
        for sym, native in VENUE_SYMBOL_MAP.get("topstep", {}).items():
            if native == intent.symbol:
                canonical = sym
                break
        if not canonical:
            # Try to infer from symbol like "ES" or "NQ"
            canonical = next(
                (s for s in FUTURES_POINT_VALUE if intent.symbol.upper().startswith(s)),
                None,
            )
        return FUTURES_POINT_VALUE.get(canonical, 1.0)
    return 1.0


def _intent_quality_score(intent: TradeIntent) -> float:
    """
    Return a normalized 0-1 quality score.

    Mean-reversion intents use quality_score / 5; FMZ/trend intents use conviction.
    This puts all signal types on the same scale so ranking is not dominated by MR.
    """
    for tag in intent.tags:
        if tag.startswith("mr_quality:"):
            try:
                return float(tag.split(":", 1)[1]) / 5.0
            except ValueError:
                break
    return intent.conviction


# Source/symbol combinations to disable based on walk-forward track record.
# The keys are thesis_id values (e.g. "fmz_strategy_4872", "mean_reversion").
DEFAULT_SOURCE_SYMBOL_DENYLIST: Dict[str, List[str]] = {
    # BTC strategy should not run on equities/indices/gold in the focus universe.
    "fmz_btc_139b": ["SPY", "QQQ", "TSLA", "GLD", "ES", "NQ", "GC", "XAUUSD"],
    # fmz_strategy_4872 is curve-fit and loses money out-of-sample. Disable it
    # across the focus universe until a robust, validated replacement is found.
    "fmz_strategy_4872": ["SPY", "QQQ", "TSLA", "GLD", "ES", "NQ", "GC", "XAUUSD"],
}


def source_symbol_allowed(thesis_id: str, symbol: str, params: Dict[str, Any]) -> bool:
    """
    Return False if a signal source has been disabled for a symbol.

    The check uses the canonical symbol (before broker mapping).  The denylist
    can be overridden in trading_params.yaml under `source_symbol_denylist`.
    """
    denylist = params.get("source_symbol_denylist", DEFAULT_SOURCE_SYMBOL_DENYLIST)
    if not isinstance(denylist, dict):
        return True
    return symbol not in denylist.get(thesis_id, [])


def rank_select_top_n(
    intents: List[TradeIntent],
    top_n: int = 2,
    score_fn: Optional[Callable[[TradeIntent], float]] = None,
) -> List[TradeIntent]:
    """
    Select the top-N intents per calendar day by expected edge.

    Mean-reversion intents use their quality score (0-5); FMZ/trend intents use
    conviction (0-1).  The score is multiplied by R:R so high-probability,
    asymmetric setups are preferred over marginal ones.
    """
    if score_fn is None:
        score_fn = _intent_quality_score
    grouped: Dict[date_cls, List[Tuple[float, TradeIntent]]] = defaultdict(list)
    for intent in intents:
        dt = getattr(intent, "created_at", None) or datetime.utcnow()
        day = dt.date() if isinstance(dt, datetime) else dt
        score = score_fn(intent) * max(intent.risk_reward_ratio, 0.1)
        grouped[day].append((score, intent))

    selected: List[TradeIntent] = []
    for items in grouped.values():
        items.sort(key=lambda x: x[0], reverse=True)
        selected.extend(intent for _, intent in items[:top_n])
    return selected


def deduplicate_intents(intents: List[TradeIntent]) -> List[TradeIntent]:
    """Keep the single best intent per symbol to avoid duplicate/over-concentrated orders."""
    best: Dict[str, TradeIntent] = {}
    dropped = 0
    for intent in intents:
        score = _intent_quality_score(intent) * max(intent.risk_reward_ratio, 0.1)
        existing = best.get(intent.symbol)
        if existing is None or score > _intent_quality_score(existing) * max(existing.risk_reward_ratio, 0.1):
            if existing is not None:
                dropped += 1
            best[intent.symbol] = intent
        else:
            dropped += 1
    if dropped:
        logger.info(f"Deduplicated {dropped} lower-conviction intent(s); kept {len(best)} unique symbols")
    return list(best.values())


def size_intent(
    intent: TradeIntent,
    account_value: float,
    config: Dict[str, Any],
    params: Dict[str, Any],
) -> TradeIntent:
    """Set intent.size based on configured risk limits and contract multiplier."""
    portfolio = config.get("portfolio", {})
    risk_pct = portfolio.get("max_risk_per_trade_pct", 0.5)
    max_pos_pct = config.get("risk_limits", {}).get("max_position_pct", 5.0)

    risk_dollars = account_value * (risk_pct / 100.0)
    max_pos_dollars = account_value * (max_pos_pct / 100.0)

    multiplier = get_contract_multiplier(intent, params)
    stop_distance = abs(intent.entry_price - intent.stop_price)
    if stop_distance <= 0:
        intent.size = 0
        return intent

    risk_per_unit = stop_distance * multiplier
    size_by_risk = risk_dollars / risk_per_unit

    if intent.venue == "topstep":
        # Futures: size is contracts; cap by exchange/account limits.
        size = int(size_by_risk)
        prop = params.get("prop_firm", {})
        max_contracts = prop.get("max_contracts", 5)
        size = max(1, min(size, max_contracts))
    elif intent.venue == "oanda":
        # Cap OANDA units by max position notional as well as by risk.
        size_by_position = max_pos_dollars / intent.entry_price if intent.entry_price > 0 else float("inf")
        size = max(1, int(min(size_by_risk, size_by_position)))
    elif "option" in intent.tags:
        # Already sized by premium budget, just ensure >=1.
        size = max(1, int(intent.size or 1))
    else:
        # Equities: size is shares, also cap by max position %.
        size_by_position = max_pos_dollars / intent.entry_price if intent.entry_price > 0 else float("inf")
        size = max(1, int(min(size_by_risk, size_by_position)))

    intent.size = size
    intent.contract_multiplier = multiplier  # type: ignore[attr-defined]
    return intent


# ──────────────────────────────────────────────────────────────────────────────
# Execution helpers
# ──────────────────────────────────────────────────────────────────────────────

def confirm_intent(intent: TradeIntent) -> bool:
    """Prompt the user for confirmation before executing a live order."""
    print(
        f"\nExecute {intent.venue.upper()} {intent.direction.upper()} "
        f"{intent.size} x {intent.symbol} @ ~{intent.entry_price:.2f}? [y/N] ",
        end="",
    )
    try:
        response = input().strip().lower()
        return response in ("y", "yes")
    except EOFError:
        return False


async def execute_option_intent(
    intent: TradeIntent, auto_confirm: bool = False
) -> Dict[str, Any]:
    """Execute an option intent directly through the Schwab adapter."""
    from tools.schwab import schwab_place_option_order

    if not auto_confirm and not confirm_intent(intent):
        return {"status": "skipped", "reason": "User declined"}

    side = "buy_to_open"
    premium_per_share = intent.entry_price / 100.0
    order_type = "LIMIT" if premium_per_share > 0 else "MARKET"
    return await schwab_place_option_order(
        symbol=intent.symbol,
        quantity=int(intent.size),
        side=side,
        order_type=order_type,
        price=round(premium_per_share, 2),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────────────

def check_backtest_guard(bypass: bool = False) -> bool:
    """
    Block live execution unless a recent backtest shows profit factor >= 1.2.

    This is the production kill-switch from the readiness checklist. Use
    --bypass-backtest-guard only for controlled manual testing.
    """
    if bypass:
        logger.warning("Backtest guard BYPASSED — live execution allowed")
        return True

    result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "backtest_focus_result.json")
    result_path = os.path.normpath(result_path)
    if not os.path.exists(result_path):
        print(
            "\n🚫 LIVE EXECUTION BLOCKED: no backtest result found.\n"
            "Run: python scripts/backtest_focus.py --days 14\n"
            "Or pass --bypass-backtest-guard to override (not recommended)."
        )
        return False

    try:
        with open(result_path) as f:
            result = json.load(f)
    except Exception as e:
        print(f"\n🚫 LIVE EXECUTION BLOCKED: could not read backtest result: {e}")
        return False

    pf = result.get("profit_factor", 0.0)
    ready = result.get("go_live_ready", False)
    if not ready:
        print(
            f"\n🚫 LIVE EXECUTION BLOCKED: backtest profit factor is {pf:.2f} "
            f"(< 1.2).\n"
            "Improve the signal engine before risking capital.\n"
            "Pass --bypass-backtest-guard to override (not recommended)."
        )
        return False

    print(f"\n✅ Backtest guard passed (profit factor {pf:.2f})")
    return True


def summarize_intent(intent: TradeIntent) -> str:
    return (
        f"{intent.symbol:12} {intent.direction.upper():5} | "
        f"entry={intent.entry_price:>10.2f} stop={intent.stop_price:>10.2f} "
        f"target={intent.target_price:>10.2f} | size={intent.size} | "
        f"venue={intent.venue} | conv={intent.conviction:.2f} | R:R={intent.risk_reward_ratio:.2f}"
    )


async def run_pipeline(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    params = load_trading_params(args.params)

    # Apply CLI overrides.
    if args.risk_per_trade is not None:
        config.setdefault("portfolio", {})
        config["portfolio"]["max_risk_per_trade_pct"] = args.risk_per_trade

    # Risk governor uses config; we enhance it below to honor contract multipliers.
    governor = RiskGovernor(config)

    api_key = args.massive_api_key or os.getenv("MASSIVE_API_KEY")
    if api_key:
        os.environ["MASSIVE_API_KEY"] = api_key

    symbols = args.symbols or list(FOCUS_SYMBOLS.keys())

    print(f"\nLive signals → TradeIntent pipeline ({datetime.utcnow().isoformat()}Z)")
    print("=" * 90)

    # Load SPY once for the broad equity-index regime filter.
    spy_df = fetch_yahoo_ohlcv("SPY", period="3mo", interval="1d")
    if spy_df is None or spy_df.empty:
        logger.warning("SPY data unavailable; equity-index regime filter disabled")
        spy_df = None

    # Load VIX for fear-gauge confirmation on long trades.
    vix_info = fetch_vix_info()
    if vix_info:
        print(f"  VIX: {vix_info['price']:.2f} ({vix_info['change_pct']:+.2f}%)")
    else:
        logger.warning("VIX data unavailable; VIX guard disabled")

    # Fetch official previous closes from Massive where available.
    massive_prices: Dict[str, float] = {}
    if api_key:
        print("Fetching Massive previous-close prices...")
        massive_prices = await fetch_massive_prev_closes(symbols, api_key)
        print(f"  Massive prices: {massive_prices}")

    # Fetch OANDA live prices for indices/commodities when available.
    # These replace the Yahoo continuous-contract proxies (which are not real futures prices).
    oanda_prices: Dict[str, float] = {}
    oanda_instrument_map = {
        "XAUUSD": "XAU/USD",
        "ES": "SPX500/USD",
        "NQ": "NAS100/USD",
        "GC": "XAU/USD",
    }
    oanda_symbols = [s for s in symbols if s in oanda_instrument_map]
    if oanda_symbols:
        print("Fetching OANDA live prices for index/commodity CFDs...")
        for sym in oanda_symbols:
            price = await fetch_oanda_price(oanda_instrument_map[sym])
            if price is not None:
                oanda_prices[sym] = price
        if oanda_prices:
            print(f"  OANDA prices: {oanda_prices}")
        else:
            print("  OANDA not configured; falling back to Yahoo proxies")

    # Fetch TopstepX live futures prices when available.
    topstep_prices: Dict[str, float] = {}
    futures_symbols = [s for s in symbols if s in ("ES", "NQ", "GC")]
    if futures_symbols:
        print("Checking TopstepX for live futures prices...")
        for fsym in futures_symbols:
            ts_price = await fetch_topstep_price(fsym)
            if ts_price:
                topstep_prices[fsym] = ts_price
        if topstep_prices:
            print(f"  Topstep prices: {topstep_prices}")
        else:
            print("  Topstep not configured; futures will use Yahoo GC=F/ES=F/NQ=F proxy")

    # Generate signals and convert to intents.
    raw_intents: List[TradeIntent] = []

    for symbol in symbols:
        yahoo_ticker = FOCUS_SYMBOLS.get(symbol, symbol)
        print(f"\n{symbol} (Yahoo: {yahoo_ticker})")
        df = fetch_yahoo_ohlcv(yahoo_ticker, period="6mo")
        if df is None or df.empty:
            print("  No market data available")
            continue

        # Load hourly chart for multi-timeframe confirmation.
        hourly_df = fetch_hourly_ohlcv(yahoo_ticker)

        candles = df_to_candles(df)
        yahoo_close = candles[-1]["close"]
        massive_close = massive_prices.get(symbol)
        topstep_close = topstep_prices.get(symbol)
        oanda_close = oanda_prices.get(symbol)

        # Venue selection: live broker price availability drives routing.
        if topstep_close is not None:
            current_price = topstep_close
            price_source = "Topstep"
            venue = "topstep"
        elif oanda_close is not None:
            current_price = oanda_close
            price_source = "OANDA"
            venue = "oanda"
        elif massive_close is not None:
            current_price = massive_close
            price_source = "Massive"
            venue = DEFAULT_VENUE_MAP.get(symbol, "schwab")
        else:
            current_price = yahoo_close
            price_source = "Yahoo"
            venue = DEFAULT_VENUE_MAP.get(symbol, "schwab")
        print(f"  Current price: {current_price:.2f} ({price_source})")

        # Gap / premarket sanity check for Schwab-listed equities/ETFs.
        # Use the latest yfinance price (pre/post/regular) instead of yesterday's close.
        gap_pct: Optional[float] = None
        gap_available = False
        if venue == "schwab":
            gap_info = fetch_latest_gap_info(symbol)
            if gap_info:
                gap_price = gap_info.get("price")
                gap_pct = gap_info.get("gap_pct")
                prev_close = gap_info.get("previous_close")
                if gap_price is not None and gap_pct is not None:
                    gap_available = True
                    current_price = gap_price
                    price_source = "yfinance live"
                    print(
                        f"  Live price: {gap_price:.2f} ({gap_pct:+.2f}% vs prev close {prev_close:.2f})"
                    )
            if not gap_available:
                print("  Live gap data unavailable for Schwab symbol")

        # Generate Massive-style signal
        mass_intents: List[TradeIntent] = []
        mass_sig = massive_style_signal(symbol, candles, current_price)
        if mass_sig and mass_sig["direction"] != "neutral":
            if not source_symbol_allowed("massive_style", symbol, params):
                print(
                    f"  Massive signal: {mass_sig['direction'].upper()} "
                    f"filtered (source disabled for {symbol})"
                )
            elif trend_aligned(df, mass_sig["direction"]):
                print(
                    f"  Massive signal: {mass_sig['direction'].upper()} "
                    f"(confidence {mass_sig['confidence']:.2f})"
                )
                intent = build_massive_intent(symbol, mass_sig, df, venue, params)
                if intent:
                    mass_intents.append(intent)
            else:
                print(
                    f"  Massive signal: {mass_sig['direction'].upper()} "
                    f"filtered (against 20-day trend)"
                )
        else:
            print(f"  Massive signal: NEUTRAL")

        # Generate FMZ quality signals
        fmz_intents: List[TradeIntent] = []
        fmz = fmz_signals_for_symbol(symbol, df)
        if fmz:
            print(f"  FMZ quality signals ({len(fmz)}):")
            for f in fmz:
                print(
                    f"    {f['strategy']}: {f['direction'].upper()} "
                    f"entry={f['entry']} stop={f['stop']} target={f['target']}"
                )
                if not source_symbol_allowed(f["strategy"], symbol, params):
                    print(f"      → filtered (source disabled for {symbol})")
                    continue
                if not trend_aligned(df, f["direction"]):
                    print("      → filtered (against 20-day trend)")
                    continue
                if venue == "oanda":
                    # OANDA symbols use the live spot price and ATR-based stops,
                    # not the futures-proxy price returned by FMZ.
                    oanda_sig = {
                        "direction": f["direction"],
                        "confidence": f["conviction"],
                        "current_price": current_price,
                    }
                    intent = build_massive_intent(symbol, oanda_sig, df, venue, params)
                    if intent:
                        fmz_intents.append(intent)
                else:
                    fmz_intents.append(build_fmz_intent(symbol, f, venue))
        else:
            print("  FMZ quality signals: none")

        # Mean-reversion signal: buy/sell stretched price back to the Bollinger mean.
        mr_intents: List[TradeIntent] = []
        mr_sig = mean_reversion_signal(symbol, df, current_price, hourly_df, vix_info)
        if mr_sig:
            print(
                f"  Mean reversion signal: {mr_sig['direction'].upper()} "
                f"(BB position {mr_sig.get('bb_position')}, RSI {mr_sig.get('rsi')}, "
                f"quality {mr_sig.get('quality_score')})"
            )
            if not source_symbol_allowed("mean_reversion", symbol, params):
                print(f"    → filtered (source disabled for {symbol})")
            elif strong_trend_aligned(df, mr_sig["direction"]):
                intent = build_mean_reversion_intent(symbol, mr_sig, df, venue, params)
                if intent:
                    mr_intents.append(intent)
            else:
                print("    → filtered (against strong trend structure)")
        else:
            print("  Mean reversion signal: none")

        # Pullback-to-trend signal for indices and high-beta equities.
        pb_intents: List[TradeIntent] = []
        pb_sig = pullback_trend_signal(symbol, df, current_price)
        if pb_sig:
            print(
                f"  Pullback trend signal: {pb_sig['direction'].upper()} "
                f"(20SMA {pb_sig.get('sma20')}, 50SMA {pb_sig.get('sma50')}, "
                f"RSI {pb_sig.get('rsi')})"
            )
            if source_symbol_allowed("pullback_trend", symbol, params):
                intent = build_pullback_trend_intent(symbol, pb_sig, df, venue, params)
                if intent:
                    pb_intents.append(intent)
            else:
                print(f"    → filtered (source disabled for {symbol})")
        else:
            print("  Pullback trend signal: none")

        # Breakout signal: quiet consolidation breakout in direction of regime.
        bo_intents: List[TradeIntent] = []
        bo_sig = breakout_signal(symbol, df, current_price)
        if bo_sig:
            print(
                f"  Breakout signal: {bo_sig['direction'].upper()} "
                f"(20SMA {bo_sig.get('sma20')}, 50SMA {bo_sig.get('sma50')}, "
                f"ATR percentile {bo_sig.get('atr_pct')})"
            )
            if source_symbol_allowed("breakout", symbol, params):
                intent = build_breakout_intent(symbol, bo_sig, df, venue, params)
                if intent:
                    bo_intents.append(intent)
            else:
                print(f"    → filtered (source disabled for {symbol})")
        else:
            print("  Breakout signal: none")

        # Combine: FMZ-confirmed trend signals + standalone MR + pullback + breakout.
        symbol_intents = confirmed_intents(mass_intents, fmz_intents) + mr_intents + pb_intents + bo_intents
        if not symbol_intents:
            print("  → filtered (no confirmed signal)")
            continue

        filtered = []
        for intent in symbol_intents:
            is_mean_reversion = intent.thesis_id == "mean_reversion"
            # Gap filter applies to trend-following only; MR wants the gap.
            if venue == "schwab" and not is_mean_reversion:
                if not gap_available:
                    print(
                        f"  {intent.thesis_id} {intent.direction} filtered "
                        f"(live gap data missing — cannot verify direction)"
                    )
                    continue
                if not gap_aligns(intent.direction, gap_pct):
                    print(
                        f"  {intent.thesis_id} {intent.direction} filtered "
                        f"(gap {gap_pct:+.2f}% against direction)"
                    )
                    continue
            is_pullback = intent.thesis_id == "pullback_trend"

            # Pullbacks are intentionally below the 20 SMA, so the strong-trend
            # filter (price >= 20 SMA) would always kill them. The pullback signal
            # already requires price > 50 SMA (long) or price < 50 SMA (short).
            if symbol in ("SPY", "QQQ", "ES", "NQ") and not is_pullback and not strong_trend_aligned(df, intent.direction):
                print(f"  {intent.thesis_id} {intent.direction} filtered (weak trend)")
                continue
            # Mean-reversion signals are allowed to trade counter to the SPY regime
            # because they are explicitly buying/selling stretched prices within a trend.
            if intent.thesis_id != "mean_reversion" and not spy_regime_aligned(symbol, intent.direction, spy_df):
                print(f"  {intent.thesis_id} {intent.direction} filtered (SPY regime mismatch)")
                continue
            if not hourly_trend_aligned(hourly_df, intent.direction):
                print(f"  {intent.thesis_id} {intent.direction} filtered (hourly trend mismatch)")
                continue
            if not momentum_aligned(df, intent.direction):
                print(f"  {intent.thesis_id} {intent.direction} filtered (momentum mismatch)")
                continue
            if intent.direction == "long" and not vix_allows_long(vix_info):
                print(
                    f"  {intent.thesis_id} {intent.direction} filtered "
                    f"(VIX {vix_info.get('price', 'n/a')} too high / spiking)"
                )
                continue
            if not await options_flow_aligned(symbol, intent.direction, config):
                print(f"  {intent.thesis_id} {intent.direction} filtered (options flow disagreement)")
                continue
            # Allow pullbacks to occur after a volatility expansion; only block
            # the very extremes (top 5% of the lookback) and extremely quiet tape.
            extreme_vol_threshold = 0.95 if is_pullback else 0.80
            if not volatility_not_extreme(df, low_pct=0.10, high_pct=extreme_vol_threshold):
                print(f"  {intent.thesis_id} {intent.direction} filtered (extreme volatility)")
                continue
            filtered.append(intent)

        raw_intents.extend(filtered)

    # Optional options layer
    if args.options:
        print("\nBuilding option intents for equity/ETF signals...")
        option_intents: List[TradeIntent] = []
        for intent in raw_intents:
            if intent.venue != "schwab" or "option" in intent.tags:
                continue
            underlying = VENUE_SYMBOL_MAP.get("schwab", {}).get(
                intent.symbol, intent.symbol
            )
            opt_intent = await build_option_intent(
                underlying,
                {
                    "direction": intent.direction,
                    "confidence": intent.conviction,
                },
                params,
            )
            if opt_intent:
                option_intents.append(opt_intent)
        raw_intents.extend(option_intents)

    # Rank across all symbols and keep only the top-N setups per calendar day.
    # This avoids over-trading correlated assets and focuses capital on the
    # highest-conviction, best R:R signals.
    raw_intents = rank_select_top_n(raw_intents, top_n=3)

    # Deduplicate: keep only the best-scoring intent per symbol.
    raw_intents = deduplicate_intents(raw_intents)

    # Size every intent
    for intent in raw_intents:
        size_intent(intent, args.account_value, config, params)

    # Validate with RiskGovernor
    portfolio_state = {
        "account_value": args.account_value,
        "day_pnl": args.day_pnl,
        "open_risk": args.open_risk,
        "consecutive_losses": args.consecutive_losses,
        "max_drawdown_pct": args.max_drawdown,
    }

    if args.use_live_portfolio:
        risk_pct = config.get("portfolio", {}).get("max_risk_per_trade_pct", 0.5)
        live_state = await fetch_portfolio_state(risk_pct)
        if live_state.get("sources"):
            portfolio_state.update(live_state)
            print(f"\nLive portfolio state ({', '.join(live_state['sources'])}):")
            print(
                f"  account_value={portfolio_state['account_value']:.2f}, "
                f"buying_power={portfolio_state['buying_power']:.2f}, "
                f"day_pnl={portfolio_state['day_pnl']:.2f}, "
                f"open_risk={portfolio_state['open_risk']:.2f}, "
                f"consecutive_losses={portfolio_state['consecutive_losses']}"
            )
        else:
            print("\nNo live broker connection available; using CLI portfolio values")

    decisions: List[Any] = await governor.validate_batch(raw_intents, portfolio_state)

    # Print summary
    print("\n" + "=" * 90)
    print("Risk Governor results")
    print("-" * 90)
    approved: List[Tuple[TradeIntent, Any]] = []
    for intent, decision in zip(raw_intents, decisions):
        line = summarize_intent(intent)
        if args.paper_trade_log:
            log_paper_trade(intent, decision, log_path=args.paper_trade_log)
        if decision.approved:
            print(f"  ✅ APPROVED  {line}")
            if decision.warnings:
                for w in decision.warnings:
                    print(f"      ⚠️  {w}")
            approved.append((intent, decision))
        else:
            print(f"  ❌ REJECTED {line}")
            print(f"      reason: {decision.rejection_reason}")

    print(f"\n{len(approved)}/{len(raw_intents)} intents approved")

    if not approved:
        print("\nNo approved intents. Nothing to execute.")
        return

    # Execution
    if args.execute:
        if not check_backtest_guard(args.bypass_backtest_guard):
            return

    if args.execute or args.simulate_execution:
        from tools.unified_execution_router import UnifiedExecutionRouter

        router = UnifiedExecutionRouter(config)
        print("\n" + "=" * 90)
        print(
            "Executing approved intents (LIVE)"
            if args.execute
            else "Simulating execution (dry-run fills)"
        )
        print("-" * 90)

        for intent, decision in approved:
            # Tag options for special handling
            is_option = "option" in intent.tags

            if is_option:
                if args.execute:
                    result = await execute_option_intent(intent, auto_confirm=args.yes)
                else:
                    result = {
                        "status": "simulated",
                        "venue": "schwab",
                        "symbol": intent.symbol,
                        "quantity": intent.size,
                        "side": "buy_to_open",
                        "note": "Option execution simulated",
                    }
            else:
                # Mark auto-confirmation on the intent so venues that require it
                # (e.g. TopstepX) can proceed.
                intent.confirmed = args.yes  # type: ignore[attr-defined]
                result = await router.execute_intent(
                    intent,
                    decision,
                    dry_run=not args.execute,
                )
                result = result.to_dict() if hasattr(result, "to_dict") else result

            status = result.get("status", result.get("success"))
            print(f"\n  {intent.symbol} → {status}")
            print(f"    method: {result.get('method', 'n/a')}")
            print(f"    order_id: {result.get('order_id', 'n/a')}")
            if result.get("fill_price"):
                print(f"    fill_price: {result['fill_price']}")
            if result.get("error"):
                print(f"    error: {result['error']}")

        await router.close_all_agents()
    else:
        print(
            "\nPass --execute to route approved intents to brokers, "
            "or --simulate-execution to see simulated fills."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live signals → TradeIntent → RiskGovernor → Execution"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Override the focus symbol list",
    )
    parser.add_argument(
        "--massive-api-key",
        default=os.getenv("MASSIVE_API_KEY"),
        help="Massive API key (defaults to MASSIVE_API_KEY env var)",
    )
    parser.add_argument(
        "--options",
        action="store_true",
        help="Also build option intents for equity/ETF signals",
    )
    parser.add_argument(
        "--account-value",
        type=float,
        default=100000.0,
        help="Account value used for position sizing",
    )
    parser.add_argument(
        "--risk-per-trade",
        type=float,
        default=None,
        help="Override max risk per trade %% of account",
    )
    parser.add_argument(
        "--day-pnl",
        type=float,
        default=0.0,
        help="Current day P&L (negative = loss)",
    )
    parser.add_argument(
        "--open-risk",
        type=float,
        default=0.0,
        help="Current open risk in dollars",
    )
    parser.add_argument(
        "--consecutive-losses",
        type=int,
        default=0,
        help="Current consecutive loss count",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=0.0,
        help="Current max drawdown %%",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to Alpha Trader config",
    )
    parser.add_argument(
        "--params",
        default="config/trading_params.yaml",
        help="Path to trading parameters",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--simulate-execution",
        action="store_true",
        help="Run approved intents through the router in dry-run mode",
    )
    group.add_argument(
        "--execute",
        action="store_true",
        help="Submit approved intents to configured brokers",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Auto-confirm every approved intent (use with extreme care)",
    )
    parser.add_argument(
        "--use-live-portfolio",
        action="store_true",
        help="Pull account value, buying power, day P&L and open risk from brokers",
    )
    parser.add_argument(
        "--bypass-backtest-guard",
        action="store_true",
        help="Allow live execution even if the backtest profit factor is below 1.2",
    )
    parser.add_argument(
        "--paper-trade-log",
        default="data/paper_trades.csv",
        help="Path to paper-trade log (CSV).  Set to empty string to disable logging.",
    )

    args = parser.parse_args()

    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
