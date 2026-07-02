"""
Profit Locking Engine for Options Trading — TIERED PARTIALS + MOMENTUM VERSION

Core philosophy: Scale out of winners like futures. Never go from green to red.
- Take 1st partial quickly to bank profit + move stop to breakeven
- Let the rest ride with a trailing stop that widens as profits grow
- If momentum is strong (underlying trending), hold through nominal targets
- If momentum fades or time decays, exit aggressively

Tier System (per contract, based on unrealized P&L):
  Tier 1 (+$40):  Sell 25%, move stop to breakeven + $0.05
  Tier 2 (+$80):  Sell 25% more, trail remaining at 30% below peak
  Tier 3 (+$150): Sell 25% more, trail remaining at 25% below peak
  Tier 4 (+$250): Sell remaining (home run), or trail at 20% below peak

If at any point we give back >50% of gains since last partial → close remaining.
Hard stop: -$100 total (account protection).
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
from loguru import logger

_STATE_PATH = "/Users/macbook/.alphatrader/data/options_position_state.json"

# ─── TIER PARAMETERS ───
# Default: scalp mode. Trend mode overrides via position state.
TIER_1_PL = 40          # Sell 50% when up $40/contract ($0.40 option move)
TIER_2_PL = 80          # Sell 25% more when up $80/contract ($0.80 option move)
TIER_3_PL = 150         # Sell 15% at +$1.50 (TREND MODE only)
TIER_4_PL = 250         # Trail last 10% at +$2.50 (TREND MODE only)

PARTIAL_SIZE_1 = 0.50   # 50%
PARTIAL_SIZE_2 = 0.25   # 25%
PARTIAL_SIZE_3 = 0.15   # 15% (trend mode)
PARTIAL_SIZE_4 = 0.10   # 10% (trend mode)

HARD_STOP_DOLLARS = -60            # Close everything if down $60 total
BREAKEVEN_BUFFER = 0.02            # Stop = avg_entry + $0.02 after Tier 1 (tight!)
GIVEBACK_PCT = 0.50                # If we give back 50% of gains since last partial, exit
MAX_HOLD_MINUTES = 20              # 20 min max — NO RUNNERS regardless of brain guidance
FLAT_EXIT_THRESHOLD = 0            # If NOT GREEN after 15 min, exit — dont let losers sit
MOMENTUM_CHECK_INTERVAL = 3        # Check if option made new high in last 3 min

# Trailing stop widths (as % below peak market value)
TRAIL_TIER_1 = 0.30     # After Tier 1 partial: 30% trail
TRAIL_TIER_2 = 0.25     # After Tier 2 partial: 25% trail
TRAIL_TIER_3 = 0.20     # After Tier 3 partial: 20% trail
TRAIL_TIER_4 = 0.15     # After Tier 4: 15% trail (tighten on big winners)

# Deep-ITM runner override: when a 0DTE option goes deep ITM quickly, force
# trend-mode behavior so we scale out instead of closing all at Tier 2.
DEEP_ITM_RUNNER_ENABLED = (
    os.getenv("DEEP_ITM_RUNNER_ENABLED", "true").lower() == "true"
)
DEEP_ITM_DELTA_THRESHOLD = float(os.getenv("DEEP_ITM_DELTA_THRESHOLD", "0.90"))


def _load_state() -> dict:
    try:
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Failed to load options state: {e}")
    return {}


def _save_state(state: dict):
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.debug(f"Failed to save options state: {e}")


def _option_key(pos: dict) -> str:
    return pos.get("option_symbol", pos.get("symbol", "UNKNOWN"))


def _get_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_deep_itm_runner(pos: dict) -> bool:
    """
    Detect a deep-ITM option runner.

    When a 0DTE option goes deep in-the-money (delta magnitude >= threshold),
    it behaves almost like stock. We want to keep a runner with a trailing stop
    instead of closing the whole position at the scalp Tier 2 target.
    """
    if not DEEP_ITM_RUNNER_ENABLED:
        return False

    option_type = pos.get("option_type", "").lower()
    if option_type not in ("call", "put"):
        return False

    try:
        from tools.schwab import get_schwab_client

        client = get_schwab_client()
        option_symbol = _option_key(pos)
        resp = client.client.get_quotes([option_symbol])
        data = resp.json()
        quote = data.get(option_symbol, {}).get("quote", {})
        delta = float(quote.get("delta", 0) or 0)

        if option_type == "put":
            return delta <= -DEEP_ITM_DELTA_THRESHOLD
        else:
            return delta >= DEEP_ITM_DELTA_THRESHOLD
    except Exception as e:
        logger.debug(f"Deep-ITM check failed for {_option_key(pos)}: {e}")
        return False


def initialize_position(pos: dict, brain_metadata: dict = None, trend_mode: str = "scalp"):
    """Record a new option position in state."""
    state = _load_state()
    key = _option_key(pos)
    brain_metadata = brain_metadata or {}
    
    if key not in state:
        state[key] = {
            "legs": [],
            "highest_unrealized_pl": 0.0,
            "highest_market_value": 0.0,
            "peak_pl_since_last_partial": 0.0,
            "tier_1_done": False,
            "tier_2_done": False,
            "tier_3_done": False,
            "tier_4_done": False,
            "breakeven_stop": None,
            "trailing_stop_pct": None,
            "original_stop": None,
            "created_at": _get_now().isoformat(),
            "last_pl_update": _get_now().isoformat(),
            "brain_score": brain_metadata.get("score", 0),
            "brain_hold_guidance": brain_metadata.get("hold_guidance", "partial_then_ride"),
            "brain_momentum": brain_metadata.get("momentum_assessment", "moderate"),
            "brain_thesis": brain_metadata.get("thesis", ""),
            "trend_mode": trend_mode,  # "scalp" or "trend"
        }
    
    entry_price = pos.get("average_price", 0)
    contracts = abs(pos.get("quantity", 0))
    
    leg = {
        "contracts": contracts,
        "entry_price": entry_price,
        "entry_time": _get_now().isoformat(),
        "status": "open",
    }
    state[key]["legs"].append(leg)
    
    total_contracts = sum(l["contracts"] for l in state[key]["legs"] if l["status"] == "open")
    total_cost = sum(l["contracts"] * l["entry_price"] for l in state[key]["legs"] if l["status"] == "open")
    avg_entry = total_cost / total_contracts if total_contracts > 0 else 0
    
    state[key]["current_contracts"] = total_contracts
    state[key]["average_entry"] = round(avg_entry, 2)
    
    if state[key]["original_stop"] is None:
        # 20% stop on the option premium
        state[key]["original_stop"] = round(avg_entry * 0.80, 2)
    
    _save_state(state)
    logger.info(f"🔵 Init position: {key} {total_contracts}cts @ {avg_entry}")


def clear_position(key: str):
    state = _load_state()
    if key in state:
        del state[key]
        _save_state(state)
        logger.info(f"🗑️ Cleared state: {key}")


async def sync_state_with_schwab():
    """Remove ghost positions from state that no longer exist in Schwab."""
    try:
        from tools.schwab import schwab_get_positions
        positions = await schwab_get_positions()
        actual_symbols = {
            p.get("option_symbol") or p.get("symbol")
            for p in positions
            if p.get("asset_type") == "OPTION"
        }
        state = _load_state()
        ghosts = [key for key in state if key not in actual_symbols]
        for key in ghosts:
            logger.warning(f"👻 Ghost position removed from state: {key}")
            del state[key]
        if ghosts:
            _save_state(state)
        logger.info(f"🔵 State sync complete: kept {len(state)}, removed {len(ghosts)} ghost(s)")
    except Exception as e:
        logger.error(f"State sync failed: {e}")


def reduce_position(key: str, contracts_closed: int):
    state = _load_state()
    if key not in state:
        return
    
    remaining = contracts_closed
    for leg in state[key]["legs"]:
        if leg["status"] == "open" and remaining > 0:
            close_amount = min(remaining, leg["contracts"])
            leg["contracts"] -= close_amount
            remaining -= close_amount
            if leg["contracts"] <= 0:
                leg["status"] = "closed"
    
    total_contracts = sum(l["contracts"] for l in state[key]["legs"] if l["status"] == "open")
    if total_contracts <= 0:
        clear_position(key)
        return
    
    total_cost = sum(l["contracts"] * l["entry_price"] for l in state[key]["legs"] if l["status"] == "open")
    state[key]["current_contracts"] = total_contracts
    state[key]["average_entry"] = round(total_cost / total_contracts, 2)
    # CRITICAL FIX: Don't reset peak to 0 — it disables giveback protection.
    # The caller (tier logic) already sets peak_pl_since_last_partial = unrealized_pl.
    # If we reset to 0 here, giveback won't trigger until new highs are made.
    # state[key]["peak_pl_since_last_partial"] = 0.0  # REMOVED — BUG
    _save_state(state)
    logger.info(f"🔻 Reduced {key}: closed {contracts_closed}, {total_contracts} remaining")


def _minutes_held(pos_state: dict) -> float:
    try:
        entry = datetime.fromisoformat(pos_state["created_at"])
        return (_get_now() - entry).total_seconds() / 60
    except Exception:
        return 0


def _pl_per_contract(unrealized_pl: float, current_contracts: int) -> float:
    return unrealized_pl / current_contracts if current_contracts > 0 else 0


def evaluate_options_positions(positions: List[dict], market_context: dict = None) -> dict:
    """
    Evaluate all open option positions with tiered partials and momentum awareness.
    
    market_context optional: {"underlying_trending": bool, "option_making_new_highs": bool}
    """
    state = _load_state()
    actions = []
    
    market_context = market_context or {}
    underlying_trending = market_context.get("underlying_trending", False)
    option_making_new_highs = market_context.get("option_making_new_highs", True)
    
    for pos in positions:
        if pos.get("asset_type") != "OPTION":
            continue
        
        key = _option_key(pos)
        contracts = abs(pos.get("quantity", 0))
        market_value = pos.get("market_value", 0)
        avg_price = pos.get("average_price", 0)
        unrealized_pl = pos.get("unrealized_pl", 0)
        bid = pos.get("bid", 0)
        ask = pos.get("ask", 0)
        
        if key not in state and contracts > 0:
            initialize_position(pos)
            state = _load_state()
        
        if key not in state:
            continue
        
        pos_state = state[key]
        is_trend = pos_state.get("trend_mode") == "trend"
        deep_itm = _is_deep_itm_runner(pos) and unrealized_pl > 0
        if deep_itm:
            is_trend = True
            logger.info(f"🚀 Deep-ITM runner override: {key} → treating as trend mode")

        current_contracts = pos_state.get("current_contracts", contracts)
        avg_entry = pos_state.get("average_entry", avg_price)
        minutes = _minutes_held(pos_state)
        pl_per = _pl_per_contract(unrealized_pl, current_contracts)
        
        # Update peaks
        if unrealized_pl > pos_state.get("highest_unrealized_pl", 0):
            pos_state["highest_unrealized_pl"] = unrealized_pl
        if market_value > pos_state.get("highest_market_value", 0):
            pos_state["highest_market_value"] = market_value
        if unrealized_pl > pos_state.get("peak_pl_since_last_partial", 0):
            pos_state["peak_pl_since_last_partial"] = unrealized_pl
        
        pos_state["last_pl_update"] = _get_now().isoformat()
        
        reason = None
        action = None
        contracts_to_close = 0
        order_type = "MARKET"
        limit_price = None
        
        # ─── 1. HARD STOP ───
        if unrealized_pl < HARD_STOP_DOLLARS:
            reason = f"HARD STOP: P&L ${unrealized_pl:.2f} < ${HARD_STOP_DOLLARS}"
            action = "close_all"
            contracts_to_close = current_contracts
        
        # ─── 2. ORIGINAL STOP (before any partials) ───
        elif not pos_state.get("tier_1_done") and not pos_state.get("breakeven_stop"):
            original_stop = pos_state.get("original_stop")
            # CRITICAL FIX: use current bid (exit price) not static avg_price
            current_mark = bid if bid > 0 else avg_price
            if original_stop and current_mark <= original_stop:
                reason = f"ORIGINAL STOP: bid ${current_mark:.2f} ≤ ${original_stop:.2f}"
                action = "close_all"
                contracts_to_close = current_contracts
        
        # ─── 3. BREAKEVEN STOP (after Tier 1) ───
        elif pos_state.get("breakeven_stop"):
            # CRITICAL FIX: use current bid (exit price) not static avg_price
            current_mark = bid if bid > 0 else avg_price
            if current_mark <= pos_state["breakeven_stop"]:
                reason = f"BREAKEVEN STOP: bid ${current_mark:.2f} ≤ ${pos_state['breakeven_stop']:.2f}"
                action = "breakeven_stop"
                contracts_to_close = current_contracts
        
        # ─── 4. TRAILING STOP (after Tier 2+) ───
        elif pos_state.get("trailing_stop_pct") and market_value > 0:
            trail_pct = pos_state["trailing_stop_pct"]
            peak_mv = pos_state.get("highest_market_value", market_value)
            stop_mv = peak_mv * (1 - trail_pct)
            if market_value <= stop_mv:
                reason = f"TRAILING STOP: mv ${market_value:.2f} ≤ ${stop_mv:.2f} (peak ${peak_mv:.2f}, trail {trail_pct:.0%})"
                action = "trailing_stop"
                contracts_to_close = current_contracts
        
        # ─── 5. GIVEBACK PROTECTION ───
        # If we gave back >50% of gains since last partial, exit remaining
        elif pos_state.get("tier_1_done") and pos_state.get("peak_pl_since_last_partial", 0) > 0:
            peak_since = pos_state["peak_pl_since_last_partial"]
            if peak_since > 10 and unrealized_pl < peak_since * (1 - GIVEBACK_PCT):
                reason = f"GIVEBACK: was +${peak_since:.0f} since last partial, now ${unrealized_pl:.2f} (>50% retracement)"
                action = "giveback_exit"
                contracts_to_close = current_contracts
        
        # ─── 6. TIERED PARTIALS ───
        if not reason:
            if not pos_state.get("tier_1_done") and pl_per >= TIER_1_PL:
                contracts_to_close = max(1, int(current_contracts * PARTIAL_SIZE_1))
                action = "tier_1_partial"
                reason = f"TIER 1 PARTIAL: ${pl_per:.0f}/ct ≥ ${TIER_1_PL} → sell {contracts_to_close}ct"
                pos_state["tier_1_done"] = True
                pos_state["breakeven_stop"] = round(avg_entry + BREAKEVEN_BUFFER, 2)
                pos_state["trailing_stop_pct"] = TRAIL_TIER_1
                pos_state["peak_pl_since_last_partial"] = unrealized_pl
                order_type = "LIMIT"
                limit_price = round(ask * 0.99, 2) if ask > 0 else None
            
            elif (pos_state.get("tier_1_done") 
                  and not pos_state.get("tier_2_done") 
                  and pl_per >= TIER_2_PL):
                if is_trend:
                    # TREND MODE: sell 25% more, keep rest for tier 3 runner
                    contracts_to_close = max(1, int(current_contracts * PARTIAL_SIZE_2))
                    action = "tier_2_partial"
                    reason = f"TIER 2 PARTIAL: ${pl_per:.0f}/ct ≥ ${TIER_2_PL} → sell {contracts_to_close}ct (trend mode)"
                    pos_state["tier_2_done"] = True
                    pos_state["trailing_stop_pct"] = TRAIL_TIER_2
                    pos_state["peak_pl_since_last_partial"] = unrealized_pl
                    order_type = "LIMIT"
                    limit_price = round(bid, 2) if bid > 0 else None
                else:
                    # SCALP MODE: sell 25% more, then CLOSE remaining
                    contracts_to_close = current_contracts  # CLOSE ALL at tier 2
                    action = "tier_2_close_all"
                    reason = f"TIER 2 CLOSE ALL: ${pl_per:.0f}/ct ≥ ${TIER_2_PL} — banking profit, no runners"
                    pos_state["tier_2_done"] = True
                    pos_state["peak_pl_since_last_partial"] = unrealized_pl
                    order_type = "LIMIT"
                    limit_price = round(bid, 2) if bid > 0 else None
            
            elif (pos_state.get("tier_2_done") 
                  and not pos_state.get("tier_3_done") 
                  and pl_per >= TIER_3_PL
                  and pos_state.get("trend_mode") == "trend"):
                contracts_to_close = max(1, int(current_contracts * PARTIAL_SIZE_3))
                action = "tier_3_partial"
                reason = f"TIER 3 PARTIAL: ${pl_per:.0f}/ct ≥ ${TIER_3_PL} → sell {contracts_to_close}ct (trend mode)"
                pos_state["tier_3_done"] = True
                pos_state["trailing_stop_pct"] = TRAIL_TIER_3
                pos_state["peak_pl_since_last_partial"] = unrealized_pl
                order_type = "LIMIT"
                limit_price = round(bid, 2) if bid > 0 else None
            
            elif (pos_state.get("tier_3_done") 
                  and not pos_state.get("tier_4_done") 
                  and pl_per >= TIER_4_PL
                  and pos_state.get("trend_mode") == "trend"):
                action = "tier_4_trail"
                reason = f"TIER 4 TRAIL: ${pl_per:.0f}/ct ≥ ${TIER_4_PL} — trend mode, trailing last 10%"
                pos_state["tier_4_done"] = True
                pos_state["trailing_stop_pct"] = TRAIL_TIER_4
                pos_state["peak_pl_since_last_partial"] = unrealized_pl
                contracts_to_close = 0  # Don't close, just update trail
        
        # ─── 7. TIME-BASED EXIT (KILL LOSERS FAST) ───
        # Scalp: 20 min max. Trend: 45 min max. Swing/weekend hold: skip time exit.
        swing_hold = pos_state.get("trend_mode") in ("swing", "weekend_hold")
        if swing_hold:
            max_hold = 999999
            flat_threshold = -999999
        else:
            max_hold = 45 if is_trend else MAX_HOLD_MINUTES
            flat_threshold = -15 if is_trend else FLAT_EXIT_THRESHOLD

        if not reason and not swing_hold and not deep_itm and minutes > max_hold:
            if unrealized_pl <= flat_threshold:
                # NOT GREEN — KILL IT. Dont let losers run.
                reason = f"TIME EXIT: held {minutes:.0f}min, P&L ${unrealized_pl:.2f} — cutting loser"
                action = "time_exit"
                contracts_to_close = current_contracts
            elif unrealized_pl > 0:
                # Small profit after time limit — TAKE IT. Dont give it back.
                reason = f"TIME EXIT (+${unrealized_pl:.2f}): held {minutes:.0f}min — banking profit before theta kills it"
                action = "time_exit_profit"
                contracts_to_close = current_contracts
                order_type = "LIMIT"
                limit_price = round(bid, 2) if bid > 0 else None
        
        # ─── BUILD ACTION ───
        if reason and action:
            actions.append({
                "symbol": key,
                "underlying": pos.get("underlying", ""),
                "action": action,
                "contracts_to_close": contracts_to_close,
                "contracts_remaining": current_contracts - contracts_to_close,
                "reason": reason,
                "unrealized_pl": unrealized_pl,
                "pl_per_contract": pl_per,
                "minutes_held": round(minutes, 1),
                "order_type": order_type,
                "limit_price": limit_price,
                "current_contracts": current_contracts,
                "tier": _tier_from_action(action),
            })
            logger.info(f"🔒 ProfitLock: {key} → {action} ({contracts_to_close}ct). {reason}")
            
            if contracts_to_close > 0:
                reduce_position(key, contracts_to_close)
    
    _save_state(state)
    
    return {
        "should_close": any(a["contracts_to_close"] > 0 for a in actions),
        "actions": actions,
        "reason": f"{len(actions)} action(s)" if actions else "All positions within limits",
    }


def _tier_from_action(action: str) -> int:
    if "tier_1" in action:
        return 1
    if "tier_2" in action:
        return 2
    if "tier_3" in action:
        return 3
    if "tier_4" in action:
        return 4
    return 0


async def evaluate_profit_locking(positions: list = None, market_context: dict = None, **kwargs) -> dict:
    """Standalone wrapper for workflow orchestrator."""
    if not positions:
        return {"should_close": False, "reason": "No open positions", "actions": []}
    return evaluate_options_positions(positions, market_context)
