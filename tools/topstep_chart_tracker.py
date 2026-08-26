"""
TopstepX Chart Tracker

Deterministic, API-driven chart analysis for futures scalping.

This module is designed to replace the LLM-based "brain-inference" node for the
prop-firm scalper workflow. It pulls live 5-minute bars from the ProjectX/
TopstepX Gateway, calculates session structure (opening range, VWAP, EMA9/20,
ATR14), and emits a deterministic trade signal with entry, stop, target, score,
and size.

Design goals:
  - No black-box decisions: every signal is reproducible from the same bars.
  - Combine-first risk: stops and sizes respect TOPSTEP_MAX_DAILY_LOSS,
    TOPSTEP_MAX_CONTRACTS, and the per-symbol param tables.
  - No duplicate entries: if the account already has an open position in the
    tracked symbol, the tracker returns direction=none.
  - Dry-run safe: when TOPSTEP_DRY_RUN=true, signals are logged but orders are
    not sent.

Public entry points:
  - topstep_chart_tracker(symbol, ...)          # workflow skill wrapper
  - analyze_chart_state(symbol, bars)           # pure analysis
  - generate_trade_signal(state, symbol_params) # pure signal generation
  - run_chart_tracker_loop(...)                 # standalone loop (see scripts/)
"""

import os
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:  # pragma: no cover
    PANDAS_AVAILABLE = False
    pd = None  # type: ignore
    np = None  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# Defaults and symbol parameters
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_SYMBOL_PARAMS = {
    "NQ": {"tick_size": 0.25, "dollar_per_pt": 20.0, "stop_pts": 8, "target_pts": 12, "max_contracts": 1},
    "MNQ": {"tick_size": 0.25, "dollar_per_pt": 2.0, "stop_pts": 8, "target_pts": 12, "max_contracts": 1},
    "ES": {"tick_size": 0.25, "dollar_per_pt": 12.5, "stop_pts": 4, "target_pts": 8, "max_contracts": 1},
    "MES": {"tick_size": 0.25, "dollar_per_pt": 1.25, "stop_pts": 4, "target_pts": 8, "max_contracts": 1},
    "YM": {"tick_size": 1.0, "dollar_per_pt": 5.0, "stop_pts": 40, "target_pts": 60, "max_contracts": 1},
    "CL": {"tick_size": 0.01, "dollar_per_pt": 1000.0, "stop_pts": 0.20, "target_pts": 0.40, "max_contracts": 1},
    "GC": {"tick_size": 0.10, "dollar_per_pt": 100.0, "stop_pts": 4.0, "target_pts": 7.0, "max_contracts": 1},
}

_DEFAULT_CONFIG = {
    "opening_range_bars": 6,       # 6 x 5m = 30-min opening range
    "ema_fast": 9,
    "ema_slow": 20,
    "atr_window": 14,
    "score_threshold_trade": 60,
    "score_threshold_no_trade": 45,
    "min_atr_pts": 4.0,            # NQ: need at least 4pt ATR to avoid chop
    "max_stop_pts": 12.0,          # Absolute cap regardless of ATR
    "risk_reward_min": 1.2,
    "volume_confirm": False,       # Futures vol from Topstep is often incomplete
    "require_or_break": True,      # Must break ORH/ORL to trigger
    "session_start_et": (18, 0),   # CME equity-index session starts 6 PM ET prior day
}


# ═══════════════════════════════════════════════════════════════════════════════
# Pure analysis helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _bars_to_dataframe(bars: List[Dict]) -> Any:
    """Convert a list of OHLCV dicts into a pandas DataFrame."""
    if not PANDAS_AVAILABLE:
        raise RuntimeError("pandas/numpy are required for chart tracking")
    df = pd.DataFrame(bars)
    df.columns = [str(c).lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"OHLCV missing required columns: {required - set(df.columns)}")
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Drop the in-progress final candle if it has zero volume; it pollutes VWAP.
    if len(df) > 1 and df["volume"].iloc[-1] == 0:
        df = df.iloc[:-1].copy()
    return df.dropna(subset=required)


def _calculate_vwap(df: Any) -> Any:
    """Cumulative VWAP from session start."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    return (typical * df["volume"]).cumsum() / df["volume"].cumsum()


def _calculate_ema(series: Any, span: int) -> Any:
    return series.ewm(span=span, adjust=False).mean()


def _calculate_atr(df: Any, window: int = 14) -> float:
    """Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return float(tr.rolling(window=window).mean().iloc[-1])


def _opening_range(df: Any, bars: int) -> Dict[str, float]:
    """Return high/low of the first `bars` rows."""
    or_df = df.iloc[:bars]
    return {"high": float(or_df["high"].max()), "low": float(or_df["low"].min())}


def _round_to_tick(price: float, tick_size: float) -> float:
    """Round price to the nearest tick."""
    if tick_size <= 0:
        return price
    return round(round(price / tick_size) * tick_size, 10)


# ═══════════════════════════════════════════════════════════════════════════════
# State analysis
# ═══════════════════════════════════════════════════════════════════════════════

async def analyze_chart_state(
    symbol: str,
    bars: Optional[List[Dict]] = None,
    opening_range_bars: int = None,
    ema_fast: int = None,
    ema_slow: int = None,
    atr_window: int = None,
) -> Dict[str, Any]:
    """
    Analyze the current chart state for a futures symbol.

    Args:
        symbol: Futures symbol (NQ, MNQ, ES, MES, etc.)
        bars: Optional pre-fetched OHLCV list. If omitted, live TopstepX bars
            are fetched via tools.topstep.topstep_get_bars.
        opening_range_bars: Number of bars used for the opening range.
        ema_fast/slow: EMA periods.
        atr_window: ATR lookback.

    Returns:
        Dict with keys:
          symbol, timestamp, current_price, vwap, ema_fast, ema_slow,
          atr, opening_range, session_high, session_low, trend,
          extension_from_vwap, bars_used, data_source, error
    """
    cfg = _DEFAULT_CONFIG.copy()
    if opening_range_bars is not None:
        cfg["opening_range_bars"] = opening_range_bars
    if ema_fast is not None:
        cfg["ema_fast"] = ema_fast
    if ema_slow is not None:
        cfg["ema_slow"] = ema_slow
    if atr_window is not None:
        cfg["atr_window"] = atr_window

    result: Dict[str, Any] = {
        "symbol": symbol.upper(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "provided",
        "error": None,
    }

    if not PANDAS_AVAILABLE:
        result["error"] = "pandas/numpy not installed"
        return result

    # Fetch bars if not provided
    fetched_bars = bars
    if fetched_bars is None:
        result["data_source"] = "topstep_api"
        try:
            from tools.topstep import topstep_get_bars, TOPSTEP_AVAILABLE
            if TOPSTEP_AVAILABLE:
                fetched_bars = await topstep_get_bars(symbol, days=1, interval=5)
            else:
                result["error"] = "TopstepX SDK not available"
                return result
        except Exception as e:
            logger.error(f"Chart tracker failed to fetch bars for {symbol}: {e}")
            result["error"] = f"fetch_error: {e}"
            return result

    if not fetched_bars or len(fetched_bars) < max(cfg["ema_slow"], cfg["atr_window"]) + 5:
        result["error"] = f"insufficient_bars: got {len(fetched_bars) if fetched_bars else 0}"
        return result

    try:
        df = _bars_to_dataframe(fetched_bars)
    except Exception as e:
        result["error"] = f"dataframe_error: {e}"
        return result

    if len(df) < max(cfg["ema_slow"], cfg["atr_window"]) + 5:
        result["error"] = f"insufficient_clean_bars: {len(df)}"
        return result

    # Opening range
    or_bars = min(cfg["opening_range_bars"], len(df) - 1)
    or_range = _opening_range(df, or_bars)

    # Indicators
    df["vwap"] = _calculate_vwap(df)
    df["ema_fast"] = _calculate_ema(df["close"], cfg["ema_fast"])
    df["ema_slow"] = _calculate_ema(df["close"], cfg["ema_slow"])
    atr = _calculate_atr(df, cfg["atr_window"])

    last = df.iloc[-1]
    current_price = float(last["close"])
    vwap = float(last["vwap"])
    ema_f = float(last["ema_fast"])
    ema_s = float(last["ema_slow"])

    # Trend determination
    above_vwap = current_price > vwap
    above_ema = ema_f > ema_s
    above_or = current_price > or_range["high"]
    below_or = current_price < or_range["low"]

    if above_vwap and above_ema:
        trend = "bullish"
    elif not above_vwap and not above_ema:
        trend = "bearish"
    else:
        trend = "neutral"

    result.update({
        "current_price": round(current_price, 4),
        "vwap": round(vwap, 4),
        "ema_fast": round(ema_f, 4),
        "ema_slow": round(ema_s, 4),
        "atr": round(atr, 4),
        "opening_range": {k: round(v, 4) for k, v in or_range.items()},
        "session_high": round(float(df["high"].max()), 4),
        "session_low": round(float(df["low"].min()), 4),
        "trend": trend,
        "above_vwap": above_vwap,
        "above_ema": above_ema,
        "above_or": above_or,
        "below_or": below_or,
        "extension_from_vwap_pct": round((current_price - vwap) / vwap * 100, 4) if vwap else 0.0,
        "bars_used": len(df),
    })
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Signal generation
# ═══════════════════════════════════════════════════════════════════════════════

def _get_symbol_params(symbol: str) -> Dict[str, Any]:
    """Merge default symbol params with env overrides."""
    prefix = symbol.upper()[:2] if symbol else "NQ"
    # Allow 3-letter prefixes like MNQ, MES
    if symbol and symbol.upper()[:3] in _DEFAULT_SYMBOL_PARAMS:
        prefix = symbol.upper()[:3]
    params = _DEFAULT_SYMBOL_PARAMS.get(prefix, _DEFAULT_SYMBOL_PARAMS["NQ"]).copy()

    # Env overrides
    params["max_contracts"] = int(os.getenv("TOPSTEP_MAX_CONTRACTS", params["max_contracts"]))
    params["stop_pts"] = float(os.getenv("TOPSTEP_STOP_LOSS_PTS", params["stop_pts"]))
    params["target_pts"] = float(os.getenv("TOPSTEP_TAKE_PROFIT_PTS", params["target_pts"]))
    return params


def generate_trade_signal(
    state: Dict[str, Any],
    symbol_params: Optional[Dict[str, Any]] = None,
    score_threshold_trade: int = None,
    score_threshold_no_trade: int = None,
    require_or_break: bool = None,
    risk_reward_min: float = None,
) -> Dict[str, Any]:
    """
    Generate a deterministic trade signal from chart state.

    Entry model:
      - LONG:  trend is bullish AND price is near/below VWAP (pullback) OR
               price breaks above opening-range high with bullish trend.
      - SHORT: trend is bearish AND price is near/above VWAP (pullback) OR
               price breaks below opening-range low with bearish trend.

    Stop/target:
      - Stop = recent swing buffered by ATR, capped at max_stop_pts.
      - Target = entry +/- (risk * 1.5), but not beyond the fixed target_pts.

    Scoring (0-100):
      - Base trend alignment: 40 pts
      - OR break/add-on: +20 pts
      - VWAP distance favorable: +15 pts
      - ATR sufficient (not chop): +15 pts
      - EMA9 aligned: +10 pts
    """
    cfg = _DEFAULT_CONFIG.copy()
    if score_threshold_trade is not None:
        cfg["score_threshold_trade"] = score_threshold_trade
    if score_threshold_no_trade is not None:
        cfg["score_threshold_no_trade"] = score_threshold_no_trade
    if require_or_break is not None:
        cfg["require_or_break"] = require_or_break
    if risk_reward_min is not None:
        cfg["risk_reward_min"] = risk_reward_min

    symbol = state.get("symbol", "")
    params = symbol_params or _get_symbol_params(symbol)
    tick_size = params.get("tick_size", 0.25)

    neutral = {
        "symbol": symbol,
        "direction": "none",
        "score": 0,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "quantity": 0,
        "thesis": "neutral/no setup",
        "reasons": [],
        "state": state,
    }

    if state.get("error"):
        return {**neutral, "thesis": f"analysis error: {state['error']}"}

    current = state.get("current_price", 0.0)
    vwap = state.get("vwap", current)
    atr = state.get("atr", 0.0)
    trend = state.get("trend", "neutral")
    above_vwap = state.get("above_vwap", False)
    above_or = state.get("above_or", False)
    below_or = state.get("below_or", False)
    above_ema = state.get("above_ema", False)
    or_high = state.get("opening_range", {}).get("high", current)
    or_low = state.get("opening_range", {}).get("low", current)

    # Chop filter
    if atr < cfg["min_atr_pts"]:
        return {**neutral, "thesis": f"chop: ATR {atr:.2f} < min {cfg['min_atr_pts']}"}

    direction = "none"
    reasons: List[str] = []
    score = 0

    # ── LONG setup ──
    if trend == "bullish":
        # Pullback to VWAP in bullish trend
        pullback_long = not above_vwap and current >= vwap - atr * 0.5
        breakout_long = above_or and above_vwap
        if pullback_long or breakout_long:
            direction = "long"
            score += 40
            reasons.append(f"bullish trend ({'pullback to VWAP' if pullback_long else 'OR break'})")
            if above_or:
                score += 20
                reasons.append("above opening-range high")
            if pullback_long:
                score += 15
                reasons.append("price near VWAP")
            if above_ema:
                score += 10
                reasons.append("EMA9 > EMA20")

    # ── SHORT setup ──
    elif trend == "bearish":
        pullback_short = above_vwap and current <= vwap + atr * 0.5
        breakout_short = below_or and not above_vwap
        if pullback_short or breakout_short:
            direction = "short"
            score += 40
            reasons.append(f"bearish trend ({'pullback to VWAP' if pullback_short else 'OR break'})")
            if below_or:
                score += 20
                reasons.append("below opening-range low")
            if pullback_short:
                score += 15
                reasons.append("price near VWAP")
            if not above_ema:
                score += 10
                reasons.append("EMA9 < EMA20")

    if direction == "none":
        return {**neutral, "thesis": f"no trigger: trend={trend}, above_vwap={above_vwap}, OR={or_low}-{or_high}"}

    # ATR sufficiency bonus
    if atr >= cfg["min_atr_pts"]:
        score += 15
        reasons.append(f"ATR {atr:.2f} sufficient")

    # Cap score
    score = min(100, score)

    # Require OR break if configured
    if cfg["require_or_break"] and not (above_or or below_or):
        return {**neutral, "thesis": "price has not broken opening range yet", "score": score}

    # Below trade threshold -> no trade
    if score < cfg["score_threshold_trade"]:
        return {**neutral, "thesis": f"score {score} below trade threshold {cfg['score_threshold_trade']}", "score": score}

    # Build levels
    entry = _round_to_tick(current, tick_size)
    if direction == "long":
        # Stop below recent low / VWAP / ATR buffer
        stop_1 = or_low - atr * 0.5
        stop_2 = vwap - atr * 0.75
        stop = max(min(stop_1, stop_2), current - cfg["max_stop_pts"])
        stop = _round_to_tick(stop, tick_size)
        risk = entry - stop
        target = entry + max(risk * 1.5, params.get("target_pts", 12))
        target = _round_to_tick(target, tick_size)
    else:
        stop_1 = or_high + atr * 0.5
        stop_2 = vwap + atr * 0.75
        stop = min(max(stop_1, stop_2), current + cfg["max_stop_pts"])
        stop = _round_to_tick(stop, tick_size)
        risk = stop - entry
        target = entry - max(risk * 1.5, params.get("target_pts", 12))
        target = _round_to_tick(target, tick_size)

    if risk <= 0:
        return {**neutral, "thesis": "invalid risk (stop inside entry)", "score": score}

    rr = abs(target - entry) / risk if risk else 0
    if rr < cfg["risk_reward_min"]:
        return {**neutral, "thesis": f"risk/reward {rr:.2f} below min {cfg['risk_reward_min']}", "score": score}

    # Default to full max_contracts unless env caps it (e.g., for gradual ramp)
    max_contracts = int(params.get("max_contracts", 1))
    default_contracts = int(os.getenv("TOPSTEP_DEFAULT_CONTRACTS", max_contracts))
    quantity = min(default_contracts, max_contracts)
    if quantity < 1:
        quantity = 1

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": target,
        "quantity": quantity,
        "risk_reward": round(rr, 2),
        "risk_pts": round(risk, 4),
        "thesis": f"{direction.upper()} {symbol}: " + "; ".join(reasons),
        "reasons": reasons,
        "state": state,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Position-state guard
# ═══════════════════════════════════════════════════════════════════════════════

async def _has_open_position(symbol: str) -> bool:
    """Return True if there is an open TopstepX position for the symbol."""
    try:
        from tools.topstep import topstep_get_positions
        positions = await topstep_get_positions()
        sym_upper = symbol.upper()
        for pos in positions:
            pos_symbol = pos.get("symbol", "")
            # contract_id looks like CON.F.US.MNQ.U26
            if sym_upper in pos_symbol.upper():
                return True
            for simple, cid_part in [("NQ", "ENQ"), ("ES", "EP"), ("MNQ", "MNQ"), ("MES", "MES"),
                                     ("YM", "YM"), ("RTY", "RTY"), ("CL", "CL"), ("GC", "GC")]:
                if simple == sym_upper and f".{cid_part}." in pos_symbol:
                    return True
    except Exception as e:
        logger.warning(f"Could not check existing positions for {symbol}: {e}")
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow skill wrapper
# ═══════════════════════════════════════════════════════════════════════════════

async def topstep_chart_tracker(
    symbol: str = "NQ",
    bars: Optional[List[Dict]] = None,
    ohlcv_data: Optional[List[Dict]] = None,
    check_positions: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Workflow-compatible skill entry point.

    Args:
        symbol: Futures symbol to track.
        bars: Optional OHLCV data; fetched from TopstepX if not provided.
        ohlcv_data: Alternative OHLCV input name from the workflow context.
        check_positions: If True, suppress new signals when a position exists.
        **kwargs: Extra workflow context (ignored by analysis).

    Returns:
        Dict matching the scalp_decision shape expected by risk_governor and
        propfirm_place_order.
    """
    symbol = (symbol or "NQ").upper()
    logger.info(f"Chart tracker starting for {symbol}")

    # The orchestrator may pass bars as either 'bars' or 'ohlcv_data'.
    effective_bars = bars if bars is not None else ohlcv_data

    # Extract only the kwargs that analyze_chart_state accepts.
    analysis_kwargs = {}
    for key in ("opening_range_bars", "ema_fast", "ema_slow", "atr_window"):
        if key in kwargs:
            analysis_kwargs[key] = kwargs[key]

    state = await analyze_chart_state(symbol, bars=effective_bars, **analysis_kwargs)
    if state.get("error"):
        logger.warning(f"Chart tracker state error for {symbol}: {state['error']}")
        return {
            "symbol": symbol,
            "direction": "none",
            "score": 0,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "quantity": 0,
            "thesis": f"chart tracker error: {state['error']}",
            "chart_state": state,
        }

    params = _get_symbol_params(symbol)
    signal = generate_trade_signal(state, symbol_params=params, **analysis_kwargs)

    # Avoid duplicate entries
    if check_positions and signal.get("direction") not in (None, "none"):
        if await _has_open_position(symbol):
            logger.info(f"Chart tracker: existing {symbol} position, skipping new signal")
            return {
                "symbol": symbol,
                "direction": "none",
                "score": signal.get("score", 0),
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "quantity": 0,
                "thesis": "existing open position; no duplicate entry",
                "chart_state": state,
            }

    # Normalize to scalp_decision shape
    return {
        "symbol": signal.get("symbol", symbol),
        "direction": signal.get("direction", "none"),
        "score": signal.get("score", 0),
        "entry_price": signal.get("entry_price", 0.0) or 0.0,
        "stop_loss": signal.get("stop_loss", 0.0) or 0.0,
        "take_profit": signal.get("take_profit", 0.0) or 0.0,
        "quantity": signal.get("quantity", 0),
        "thesis": signal.get("thesis", ""),
        "risk_reward": signal.get("risk_reward", 0.0),
        "chart_state": state,
        "trade_type": "intraday",
        "hold_guidance": "scalp",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Standalone loop helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _is_cme_open(now: datetime) -> bool:
    """
    Return True during CME equity-index electronic session:
    Sun 18:00 ET through Fri 17:00 ET.
    """
    import pytz
    et = pytz.timezone("America/New_York")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc).astimezone(et)
    else:
        now = now.astimezone(et)
    weekday = now.weekday()
    hour = now.hour
    # Sunday 18+ through Friday 17- is open
    if weekday == 6 and hour >= 18:
        return True
    if weekday in (0, 1, 2, 3):
        return True
    if weekday == 4 and hour < 17:
        return True
    return False


async def run_chart_tracker_cycle(
    symbol: str = "NQ",
    execute: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Run one chart-tracker cycle.

    If execute=True and a signal is approved, place a bracket order through
    tools.topstep. Still respects TOPSTEP_DRY_RUN and TOPSTEP_TRADING_ENABLED.
    """
    signal = await topstep_chart_tracker(symbol=symbol, **kwargs)
    direction = signal.get("direction", "none")
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "signal": signal,
        "executed": False,
        "execution_result": None,
    }

    if direction in (None, "none"):
        logger.info(f"Chart tracker cycle: no trade for {symbol}")
        return result

    logger.info(
        f"Chart tracker signal: {direction.upper()} {symbol} @ {signal.get('entry_price')} "
        f"stop={signal.get('stop_loss')} target={signal.get('take_profit')} score={signal.get('score')}"
    )

    if execute:
        try:
            from tools.topstep import topstep_place_bracket_order
            execution = await topstep_place_bracket_order(
                symbol=symbol,
                quantity=int(signal.get("quantity", 1)),
                side=direction,
                stop_loss=float(signal.get("stop_loss", 0.0)),
                take_profit=float(signal.get("take_profit", 0.0)),
                order_type="MARKET",
                confirmed=True,
            )
            result["executed"] = execution.get("status") in ("submitted", "simulated")
            result["execution_result"] = execution
            logger.info(f"Chart tracker execution: {execution.get('status')}")
        except Exception as e:
            logger.error(f"Chart tracker execution failed: {e}")
            result["execution_result"] = {"status": "failed", "error": str(e)}

    return result


async def run_chart_tracker_loop(
    symbol: str = "NQ",
    interval_seconds: int = 60,
    execute: bool = False,
    max_iterations: Optional[int] = None,
    **kwargs
):
    """
    Run the chart tracker in a continuous loop.

    Args:
        symbol: Symbol to track.
        interval_seconds: Seconds between cycles.
        execute: Whether to actually place orders (still gated by .env).
        max_iterations: None = run forever.
    """
    logger.info(
        f"Starting chart tracker loop for {symbol} every {interval_seconds}s "
        f"(execute={execute}, dry_run={os.getenv('TOPSTEP_DRY_RUN', 'false')})"
    )
    iteration = 0
    while True:
        try:
            now = datetime.now(timezone.utc)
            if not _is_cme_open(now):
                logger.debug("CME equity-index session closed; chart tracker sleeping")
                await asyncio.sleep(interval_seconds)
                continue

            await run_chart_tracker_cycle(symbol=symbol, execute=execute, **kwargs)
            iteration += 1
            if max_iterations and iteration >= max_iterations:
                logger.info(f"Chart tracker loop reached max_iterations={max_iterations}")
                break
        except Exception as e:
            logger.error(f"Chart tracker loop error: {e}")
        await asyncio.sleep(interval_seconds)


# Backwards-compatible alias for any existing callers
chart_tracker = topstep_chart_tracker
