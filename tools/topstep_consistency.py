"""
Topstep Combine Consistency Enforcer — CONSERVATIVE PASS

Goal: Pass the $50K combine in 2 days with minimum $1,500/day.
Best day of $13,508.60 is LOCKED. We only need consistency.

Strategy:
- Trade 1-2 contracts on NQ MAX
- 8pt stop = $160-320 risk per trade
- 12pt target = $240-480 gain per trade
- Close ALL at target — no runners
- 30 min time exit max
- If up $1,500/day: STOP (we passed)
- If down $500/day: STOP (protect capital)

NEVER exceed daily profit cap — would reset consistency ratio.
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from loguru import logger

# ─── CONSERVATIVE PARAMETERS ───
# Env overrides allow the enforcer to stay in sync with the live combine account.
DAILY_PROFIT_CAP = float(os.getenv("TOPSTEP_DAILY_PROFIT_CAP", 1500))
# TOPSTEP_MAX_DAILY_LOSS is stored as a positive dollar value in .env
DAILY_LOSS_LIMIT = -float(os.getenv("TOPSTEP_MAX_DAILY_LOSS", 1800))
MAX_CONTRACTS = int(os.getenv("TOPSTEP_MAX_CONTRACTS", 1))
PROFIT_TARGET_PER_TRADE = 12      # 12 NQ points = $240-480 (1-2 contracts)
STOP_LOSS_PER_TRADE = 8           # 8 NQ points = $160-320 (1-2 contracts)
MIN_TRADING_DAYS = 2              # Only need 2 days minimum for consistency
BEST_DAY_LOCKED = 13508.60        # Current best day — NEVER exceed this

_STATE_PATH = Path("/Users/macbook/.alphatrader/data/topstep_consistency_state.json")


def _load_state() -> dict:
    try:
        if _STATE_PATH.exists():
            with open(_STATE_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Failed to load topstep consistency state: {e}")
    return {}


def _save_state(state: dict):
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.debug(f"Failed to save topstep consistency state: {e}")


def _today() -> str:
    # Use ET date since trading sessions span ET midnight
    from pytz import timezone as tz
    et = tz("America/New_York")
    return datetime.now(et).strftime("%Y-%m-%d")


def get_consistency_status() -> Dict:
    state = _load_state()
    today = _today()
    
    daily_pnl = state.get("daily_pnl", {})
    today_pnl = daily_pnl.get(today, 0)
    
    total_days = len(daily_pnl)
    total_profits = sum(v for v in daily_pnl.values() if v > 0)
    total_losses = sum(v for v in daily_pnl.values() if v < 0)
    net_pnl = sum(daily_pnl.values())
    
    best_day = max(daily_pnl.values()) if daily_pnl else 0
    # Include the locked best day from before automation
    effective_best_day = max(best_day, BEST_DAY_LOCKED)
    
    # Consistency calc
    consistency_ratio = effective_best_day / total_profits if total_profits > 0 else 0
    passes_consistency = consistency_ratio <= 0.40
    
    # How much more to pass
    additional_needed = 0
    if not passes_consistency and effective_best_day > 0:
        required_total = effective_best_day / 0.40
        additional_needed = max(0, required_total - total_profits)
    
    # Days to pass at current pace
    days_to_pass = 0
    if additional_needed > 0 and today_pnl > 0:
        days_to_pass = int(additional_needed / today_pnl) if today_pnl > 0 else 99
    
    can_trade = True
    reasons = []
    
    if today_pnl >= DAILY_PROFIT_CAP:
        can_trade = False
        reasons.append(f"🎯 DAILY CAP HIT: +${today_pnl:.2f} / ${DAILY_PROFIT_CAP} — STOP TRADING TODAY")
    
    if today_pnl <= DAILY_LOSS_LIMIT:
        can_trade = False
        reasons.append(f"🛑 DAILY LOSS LIMIT: ${today_pnl:.2f} / ${DAILY_LOSS_LIMIT}")
    
    # Warning if approaching best day
    if today_pnl > BEST_DAY_LOCKED * 0.50 and today_pnl < DAILY_PROFIT_CAP:
        reasons.append(f"⚠️ APPROACHING BEST DAY: ${today_pnl:.2f} / ${BEST_DAY_LOCKED} — be careful")
    
    return {
        "can_trade": can_trade,
        "reasons": reasons,
        "today_pnl": today_pnl,
        "daily_profit_cap": DAILY_PROFIT_CAP,
        "daily_loss_limit": DAILY_LOSS_LIMIT,
        "max_contracts": MAX_CONTRACTS,
        "total_trading_days": total_days,
        "total_profits": round(total_profits, 2),
        "total_losses": round(total_losses, 2),
        "net_pnl": round(net_pnl, 2),
        "best_day": round(effective_best_day, 2),
        "consistency_ratio": round(consistency_ratio, 3),
        "passes_consistency": passes_consistency,
        "additional_profit_needed": round(additional_needed, 2),
        "estimated_days_remaining": days_to_pass,
        "min_days_needed": max(0, MIN_TRADING_DAYS - total_days),
        "profit_target_per_trade": PROFIT_TARGET_PER_TRADE,
        "stop_loss_per_trade": STOP_LOSS_PER_TRADE,
    }


def record_daily_pnl(pnl: float, date: str = None):
    state = _load_state()
    if "daily_pnl" not in state:
        state["daily_pnl"] = {}
    
    date = date or _today()
    state["daily_pnl"][date] = state["daily_pnl"].get(date, 0) + pnl
    
    _save_state(state)
    logger.info(f"📊 Topstep P&L {date}: ${pnl:+.2f} (running: ${state['daily_pnl'][date]:+.2f})")


def reset_daily_tracking():
    state = _load_state()
    today = _today()
    if "daily_pnl" in state and today in state["daily_pnl"]:
        del state["daily_pnl"][today]
        _save_state(state)
        logger.warning(f"Reset Topstep daily tracking for {today}")


async def topstep_consistency_enforcer(**kwargs) -> Dict:
    """Return consistency status using the LIVE TopstepX balance/PnL."""
    status = get_consistency_status()
    try:
        from tools.topstep import topstep_check_compliance
        compliance = await topstep_check_compliance()
        if compliance.get("status") == "error":
            logger.warning(
                f"Consistency enforcer could not fetch live compliance: {compliance.get('reason')}"
            )
            return status

        balance = float(compliance.get("balance", 0))
        starting_balance = float(compliance.get("starting_balance", balance))
        real_today_pnl = balance - starting_balance

        status["today_pnl"] = real_today_pnl
        status["balance"] = balance
        status["starting_balance"] = starting_balance
        status["daily_loss_used"] = compliance.get(
            "daily_loss_used", max(0.0, starting_balance - balance)
        )
        status["max_contracts"] = compliance.get("max_contracts", MAX_CONTRACTS)

        # Re-evaluate trading permission against live PnL
        if real_today_pnl >= DAILY_PROFIT_CAP:
            status["can_trade"] = False
            status["reasons"].append(
                f"🎯 DAILY CAP HIT: +${real_today_pnl:.2f} / ${DAILY_PROFIT_CAP:.2f} — STOP TRADING TODAY"
            )
        if real_today_pnl <= DAILY_LOSS_LIMIT:
            status["can_trade"] = False
            status["reasons"].append(
                f"🛑 DAILY LOSS LIMIT: ${real_today_pnl:.2f} ≤ ${DAILY_LOSS_LIMIT:.2f}"
            )
    except Exception as e:
        logger.error(f"Consistency enforcer live balance fetch failed: {e}")
    return status
