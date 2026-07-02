"""
Circuit Breakers — Hard Safety Limits

Enforced BEFORE any trade is placed. These are non-negotiable.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from loguru import logger

_STATE_PATH = "/Users/macbook/.alphatrader/data/circuit_breaker_state.json"

# ─── DEFAULT LIMITS (override via config/trading_params.yaml) ───
DEFAULT_DAILY_LOSS_HALT = -500
DEFAULT_CONSECUTIVE_LOSSES = 3
DEFAULT_OPTIONS_DOWN_PCT = 30
DEFAULT_FUTURES_DOWN_DOLLARS = 200
DEFAULT_EMERGENCY_EQUITY_FLOOR = 49000


def _load_state() -> dict:
    try:
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"CB state load error: {e}")
    return {}


def _save_state(state: dict):
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.debug(f"CB state save error: {e}")


def _today_str() -> str:
    """Return ET date string for daily tracking."""
    from pytz import timezone as tz
    et = tz("America/New_York")
    return datetime.now(et).strftime("%Y-%m-%d")


def check_circuit_breakers(
    daily_pnl: float = 0.0,
    consecutive_losses: int = 0,
    open_futures_positions: list = None,
    open_options_positions: list = None,
    account_equity: float = None,
    custom_limits: dict = None,
) -> Dict:
    """
    Check all circuit breakers. Returns {"halted": bool, "reason": str}.
    
    Call this at the START of every trading cycle before placing orders.
    """
    open_futures_positions = open_futures_positions or []
    open_options_positions = open_options_positions or []
    custom_limits = custom_limits or {}
    state = _load_state()
    today = _today_str()
    
    # Daily reset
    if state.get("last_check_date") != today:
        state["daily_pnl"] = 0.0
        state["consecutive_losses"] = 0
        state["halted_until"] = None
        state["last_check_date"] = today
    
    # Check if currently halted
    halted_until = state.get("halted_until")
    if halted_until:
        try:
            halt_dt = datetime.fromisoformat(halted_until)
            if datetime.now(timezone.utc) < halt_dt:
                return {"halted": True, "reason": f"Trading halted until {halted_until}"}
        except Exception:
            pass
        state["halted_until"] = None
    
    daily_loss_limit = custom_limits.get("daily_loss_halt", DEFAULT_DAILY_LOSS_HALT)
    consec_limit = custom_limits.get("consecutive_losses_halt", DEFAULT_CONSECUTIVE_LOSSES)
    options_down_pct = custom_limits.get("options_down_pct_halt", DEFAULT_OPTIONS_DOWN_PCT)
    futures_down_dollars = custom_limits.get("futures_down_dollars_halt", DEFAULT_FUTURES_DOWN_DOLLARS)
    equity_floor = custom_limits.get("emergency_equity_floor", DEFAULT_EMERGENCY_EQUITY_FLOOR)
    
    # 1. Daily loss halt
    state["daily_pnl"] = state.get("daily_pnl", 0) + daily_pnl
    if state["daily_pnl"] <= daily_loss_limit:
        _halt_for_hours(state, 24)
        _save_state(state)
        logger.error(f"🛑 CIRCUIT BREAKER: Daily loss ${state['daily_pnl']:.0f} ≤ ${daily_loss_limit}. HALT 24h.")
        return {"halted": True, "reason": f"Daily loss halt: ${state['daily_pnl']:.0f}"}
    
    # 2. Consecutive losses halt
    if daily_pnl < 0:
        state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
    elif daily_pnl > 0:
        state["consecutive_losses"] = 0
    
    if state["consecutive_losses"] >= consec_limit:
        _halt_for_hours(state, 2)
        _save_state(state)
        logger.error(f"🛑 CIRCUIT BREAKER: {state['consecutive_losses']} consecutive losses. HALT 2h.")
        return {"halted": True, "reason": f"Consecutive loss halt: {state['consecutive_losses']} losses"}
    
    # 3. Emergency equity floor (Topstep combine)
    if account_equity is not None and account_equity < equity_floor:
        logger.error(f"🛑 CIRCUIT BREAKER: Equity ${account_equity:.0f} < floor ${equity_floor}. EMERGENCY STOP.")
        return {
            "halted": True,
            "reason": f"EMERGENCY: Equity ${account_equity:.0f} below floor ${equity_floor}",
            "emergency": True,
        }
    
    # 4. Options down % — close immediately but don't halt
    for pos in open_options_positions:
        unrealized_pl = pos.get("unrealized_pl", 0)
        market_value = pos.get("market_value", 0)
        # Estimate entry cost from unrealized_pl + market_value
        entry_cost = market_value - unrealized_pl
        if entry_cost > 0 and unrealized_pl < 0:
            down_pct = abs(unrealized_pl) / entry_cost * 100
            if down_pct >= options_down_pct:
                logger.error(f"🛑 CIRCUIT BREAKER: Option {pos.get('symbol')} down {down_pct:.0f}%. CLOSE.")
                return {
                    "halted": False,
                    "reason": f"Option down {down_pct:.0f}%",
                    "close_positions": [pos],
                }
    
    # 5. Futures down $ — close immediately but don't halt
    for pos in open_futures_positions:
        unrealized_pl = pos.get("unrealized_pl", 0)
        if unrealized_pl <= -futures_down_dollars:
            logger.error(f"🛑 CIRCUIT BREAKER: Futures {pos.get('symbol')} down ${abs(unrealized_pl):.0f}. FLATTEN.")
            return {
                "halted": False,
                "reason": f"Futures down ${abs(unrealized_pl):.0f}",
                "close_positions": [pos],
            }
    
    _save_state(state)
    return {"halted": False, "reason": "All clear"}


def _halt_for_hours(state: dict, hours: int):
    state["halted_until"] = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def record_trade_result(pnl: float):
    """Record a trade result for consecutive loss tracking."""
    state = _load_state()
    today = _today_str()
    if state.get("last_check_date") != today:
        state["daily_pnl"] = 0.0
        state["consecutive_losses"] = 0
        state["last_check_date"] = today
    
    state["daily_pnl"] = state.get("daily_pnl", 0) + pnl
    if pnl < 0:
        state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
    elif pnl > 0:
        state["consecutive_losses"] = 0
    
    _save_state(state)
    logger.info(f"Circuit breaker: recorded P&L ${pnl:.2f}, daily=${state['daily_pnl']:.2f}, streak={state['consecutive_losses']}")


def reset_circuits():
    """Manual reset — use with caution."""
    state = _load_state()
    state["halted_until"] = None
    state["daily_pnl"] = 0.0
    state["consecutive_losses"] = 0
    state["last_check_date"] = _today_str()
    _save_state(state)
    logger.warning("Circuit breakers manually reset")
