"""Unit tests for tools/topstep_chart_tracker.py.

These tests use synthetic bars and do not touch the TopstepX API.
"""

import pytest
import os
import sys
from pathlib import Path

# Ensure repo root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.topstep_chart_tracker import (
    analyze_chart_state,
    generate_trade_signal,
    topstep_chart_tracker,
    _get_symbol_params,
)


def _make_bars(trend: str, n: int = 60, base_price: float = 20000.0, atr: float = 10.0):
    """Generate a synthetic 5-minute OHLCV list."""
    bars = []
    price = base_price
    for i in range(n):
        if trend == "bullish":
            drift = atr * 0.05
        elif trend == "bearish":
            drift = -atr * 0.05
        else:
            drift = 0.0
        noise = (i % 5 - 2) * atr * 0.1
        open_p = price + noise
        close_p = open_p + drift + noise * 0.3
        high_p = max(open_p, close_p) + atr * 0.3
        low_p = min(open_p, close_p) - atr * 0.3
        bars.append({
            "timestamp": f"2026-07-08T09:{i:02d}:00-04:00",
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": 1000 + i * 10,
        })
        price = close_p
    return bars


@pytest.mark.asyncio
async def test_analyze_chart_state_bullish():
    bars = _make_bars("bullish", n=60)
    state = await analyze_chart_state("NQ", bars=bars)
    assert state["error"] is None
    assert state["trend"] == "bullish"
    assert state["current_price"] > state["vwap"]
    assert state["ema_fast"] > state["ema_slow"]
    assert state["atr"] > 0


@pytest.mark.asyncio
async def test_analyze_chart_state_bearish():
    bars = _make_bars("bearish", n=60)
    state = await analyze_chart_state("NQ", bars=bars)
    assert state["error"] is None
    assert state["trend"] == "bearish"
    assert state["current_price"] < state["vwap"]
    assert state["ema_fast"] < state["ema_slow"]


def test_generate_trade_signal_long_breakout():
    bars = _make_bars("bullish", n=60)
    # analyze_chart_state is async, but generate_trade_signal is pure sync
    import asyncio
    state = asyncio.run(analyze_chart_state("NQ", bars=bars))
    # Force above opening range so the breakout path is taken
    state["above_or"] = True
    signal = generate_trade_signal(state)
    assert signal["direction"] == "long"
    assert signal["score"] >= 60
    assert signal["entry_price"] > 0
    assert signal["stop_loss"] < signal["entry_price"]
    assert signal["take_profit"] > signal["entry_price"]
    assert signal["risk_reward"] >= 1.2


def test_generate_trade_signal_short_breakout():
    bars = _make_bars("bearish", n=60)
    import asyncio
    state = asyncio.run(analyze_chart_state("NQ", bars=bars))
    state["below_or"] = True
    signal = generate_trade_signal(state)
    assert signal["direction"] == "short"
    assert signal["score"] >= 60
    assert signal["stop_loss"] > signal["entry_price"]
    assert signal["take_profit"] < signal["entry_price"]


def test_generate_trade_signal_no_trade_in_chop():
    bars = _make_bars("neutral", n=60, atr=1.0)
    import asyncio
    state = asyncio.run(analyze_chart_state("NQ", bars=bars))
    signal = generate_trade_signal(state)
    assert signal["direction"] == "none"
    assert "chop" in signal["thesis"].lower() or "atr" in signal["thesis"].lower()


def test_generate_trade_signal_require_or_break_blocks_early():
    bars = _make_bars("bullish", n=60)
    import asyncio
    state = asyncio.run(analyze_chart_state("NQ", bars=bars))
    # Force a valid pullback setup but without an opening-range break
    state["above_or"] = False
    state["below_or"] = False
    signal = generate_trade_signal(state, require_or_break=True)
    assert signal["direction"] == "none"


def test_get_symbol_params_env_override():
    os.environ["TOPSTEP_STOP_LOSS_PTS"] = "6"
    os.environ["TOPSTEP_TAKE_PROFIT_PTS"] = "10"
    params = _get_symbol_params("NQ")
    assert params["stop_pts"] == 6.0
    assert params["target_pts"] == 10.0
    del os.environ["TOPSTEP_STOP_LOSS_PTS"]
    del os.environ["TOPSTEP_TAKE_PROFIT_PTS"]


@pytest.mark.asyncio
async def test_topstep_chart_tracker_wrapper_no_position(monkeypatch):
    bars = _make_bars("bullish", n=60)
    state = await analyze_chart_state("NQ", bars=bars)
    state["above_or"] = True

    async def fake_has_open(symbol):
        return False

    import tools.topstep_chart_tracker as ctracker
    monkeypatch.setattr(ctracker, "_has_open_position", fake_has_open)

    decision = await topstep_chart_tracker("NQ", bars=bars)
    assert decision["symbol"] == "NQ"
    assert decision["direction"] == "long"
    assert decision["score"] >= 60
    assert decision["entry_price"] > 0
    assert decision["stop_loss"] > 0
    assert decision["take_profit"] > 0


@pytest.mark.asyncio
async def test_topstep_chart_tracker_wrapper_existing_position(monkeypatch):
    bars = _make_bars("bullish", n=60)

    async def fake_has_open(symbol):
        return True

    import tools.topstep_chart_tracker as ctracker
    monkeypatch.setattr(ctracker, "_has_open_position", fake_has_open)

    decision = await topstep_chart_tracker("NQ", bars=bars)
    assert decision["direction"] == "none"
    assert "existing open position" in decision["thesis"].lower()


@pytest.mark.asyncio
async def test_topstep_chart_tracker_wrapper_error():
    decision = await topstep_chart_tracker("NQ", bars=[])
    assert decision["direction"] == "none"
    assert "error" in decision["thesis"].lower()


def test_topstep_trade_critique_no_trade():
    from tools.brain import topstep_trade_critique
    import asyncio
    result = asyncio.run(topstep_trade_critique("NQ", scalp_decision={"direction": "none"}))
    inner = result.get("result", result)
    assert inner["approved"] is False
    assert inner["verdict"] == "NO_TRADE"


def test_topstep_trade_critique_missing_data_rejects():
    from tools.brain import topstep_trade_critique
    import asyncio
    scalp = {
        "symbol": "NQ",
        "direction": "long",
        "score": 85,
        "entry_price": 29500.0,
        "stop_loss": 29490.0,
        "take_profit": 29520.0,
    }
    result = asyncio.run(topstep_trade_critique("NQ", scalp_decision=scalp))
    inner = result.get("result", result)
    assert inner["approved"] is False
    assert inner["verdict"] == "REJECT"
