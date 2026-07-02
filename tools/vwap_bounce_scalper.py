"""
QQQ VWAP Bounce Scalper

Intraday mean-reversion strategy for Schwab options:
- Watch QQQ 1-minute price vs VWAP
- When price dips below VWAP and reclaims it on a green candle, buy an
  ATM 0DTE call with a tight stop and quick profit target.

Designed to catch moves like QQQ 704 -> 710 off the VWAP reclaim.
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from tools.options_multi_scalper import _target_expiration_for_hold, SWING_HOLD_ON_FRIDAY

SYMBOL = "QQQ"


def _fetch_1m_data(symbol: str = SYMBOL) -> List[Dict]:
    """Fetch recent 1-minute OHLCV from Yahoo Finance."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="1m")
        if hist.empty:
            return []
        candles = []
        for idx, row in hist.iterrows():
            candles.append({
                "timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        return candles
    except Exception as e:
        logger.warning(f"VWAP scalper: failed to fetch 1m data for {symbol}: {e}")
        return []


def _calculate_vwap(candles: List[Dict]) -> Optional[float]:
    """Return the current VWAP from the provided 1m candles."""
    if not candles:
        return None
    try:
        cumulative_tp_vol = 0.0
        cumulative_vol = 0
        for c in candles:
            typical = (c["high"] + c["low"] + c["close"]) / 3.0
            vol = max(c["volume"], 0)
            cumulative_tp_vol += typical * vol
            cumulative_vol += vol
        return cumulative_tp_vol / cumulative_vol if cumulative_vol > 0 else None
    except Exception as e:
        logger.warning(f"VWAP calc error: {e}")
        return None


def _vwap_signal(candles: List[Dict]) -> Dict:
    """
    Generate a long/short signal based on VWAP reclaim.

    Long: previous candle low <= VWAP, current close > VWAP, current green,
          current close not more than 0.15% above VWAP (no chasing).
    """
    if len(candles) < 20:
        return {"signal": "none", "confidence": 0, "reason": "not enough 1m data"}

    vwap = _calculate_vwap(candles)
    if vwap is None or vwap <= 0:
        return {"signal": "none", "confidence": 0, "reason": "VWAP unavailable"}

    prev = candles[-2]
    curr = candles[-1]

    avg_volume = sum(c["volume"] for c in candles[-20:]) / 20.0

    long_reclaim = (
        prev["low"] <= vwap * 1.0005
        and curr["close"] > vwap
        and curr["close"] > curr["open"]
        and curr["close"] < vwap * 1.0015
    )
    volume_confirm = curr["volume"] >= avg_volume * 0.7

    if long_reclaim and volume_confirm:
        distance = (curr["close"] - vwap) / vwap * 100
        confidence = min(70 + int(distance * 10), 90)
        return {
            "signal": "long",
            "confidence": confidence,
            "vwap": round(vwap, 2),
            "price": round(curr["close"], 2),
            "reason": f"QQQ reclaimed VWAP {round(vwap, 2)} on green volume candle",
        }

    return {"signal": "none", "confidence": 0, "vwap": round(vwap, 2), "reason": "no reclaim"}


async def run_qqq_vwap_bounce(orchestrator=None) -> Dict:
    """Main entry point for the QQQ VWAP bounce scalper."""
    from tools.schwab import (
        schwab_check_compliance,
        schwab_get_positions,
        schwab_get_option_chain_parsed,
        schwab_place_option_order,
    )
    from tools.profit_locking_engine import initialize_position

    result = {"action": "none", "reason": "", "order": None}

    # Swing / weekend hold mode
    swing_mode = SWING_HOLD_ON_FRIDAY and datetime.now().weekday() == 4
    target_exp = _target_expiration_for_hold(swing_mode)
    trend_mode = "weekend_hold" if swing_mode else "scalp"

    # 1. Market hours sanity check (ET)
    try:
        import pytz
        et = pytz.timezone("America/New_York")
        now = datetime.now(et)
        if now.weekday() >= 5 or now.hour < 9 or (now.hour == 9 and now.minute < 30) or now.hour >= 16:
            result["reason"] = "Outside equity market hours"
            logger.info(f"VWAP scalper: {result['reason']}")
            return result
    except Exception:
        pass

    # 2. Compliance
    compliance = await schwab_check_compliance()
    if not compliance.get("can_trade", True):
        result["reason"] = f"Compliance: {compliance.get('reason')}"
        logger.warning(f"VWAP scalper: {result['reason']}")
        return result

    # 3. Position checks
    positions = await schwab_get_positions()
    option_positions = [p for p in positions if p.get("asset_type") == "OPTION"]
    if len(option_positions) >= 2:
        result["reason"] = "Max 2 concurrent option positions"
        return result
    if any(SYMBOL in (p.get("symbol") or "") for p in option_positions):
        result["reason"] = f"Already have a {SYMBOL} option position"
        return result

    # 4. VWAP signal
    candles = _fetch_1m_data(SYMBOL)
    signal = _vwap_signal(candles)
    if signal.get("signal") != "long":
        result["reason"] = signal.get("reason", "no signal")
        logger.info(f"VWAP scalper: {result['reason']}")
        return result

    logger.info(f"VWAP scalper signal: {signal}")

    # 5. Fetch option chain (calls for long rebound)
    option_chain = await schwab_get_option_chain_parsed(SYMBOL, direction="long", expiration=target_exp)
    if "error" in option_chain:
        result["reason"] = f"Option chain error: {option_chain['error']}"
        logger.warning(result["reason"])
        return result

    underlying_price = option_chain.get("underlying_price", signal["price"])
    strikes = option_chain.get("strikes", [])
    if not strikes:
        result["reason"] = "No strikes returned"
        return result

    # 6. Pick ATM call
    atm_strike = None
    atm_data = None
    min_dist = float("inf")
    for s in strikes:
        dist = abs(s["strike"] - underlying_price)
        if dist < min_dist:
            min_dist = dist
            atm_strike = s["strike"]
            atm_data = s

    if not atm_strike or not atm_data:
        result["reason"] = "Could not find ATM strike"
        return result

    # 7. Build option symbol
    expiration = option_chain.get("expiration", datetime.now().strftime("%Y-%m-%d"))
    exp_str = datetime.strptime(expiration, "%Y-%m-%d").strftime("%y%m%d")
    strike_str = f"{int(atm_strike * 1000):08d}"
    option_symbol = f"{SYMBOL:<6}{exp_str}C{strike_str}"

    # 8. Limit price at mid, never above ask
    bid = atm_data.get("bid", 0)
    ask = atm_data.get("ask", 0)
    if bid and ask:
        limit_price = round(bid + (ask - bid) * 0.5, 2)
    else:
        limit_price = round(atm_data.get("last", atm_strike * 0.01), 2)

    if limit_price <= 0:
        result["reason"] = "Invalid limit price"
        return result

    # 9. Size: 1 contract base, 2 only if BP comfortably allows
    buying_power = compliance.get("buying_power", 0)
    quantity = 1
    if buying_power >= limit_price * 100 * 2 * 1.2:
        quantity = 2

    max_cost = buying_power * 0.25
    estimated_cost = limit_price * 100 * quantity
    if estimated_cost > max_cost:
        quantity = max(1, int(max_cost / (limit_price * 100)))

    logger.info(
        f"VWAP scalper entry: {SYMBOL} CALL {atm_strike} | qty {quantity} @ ${limit_price} | vwap {signal['vwap']}"
    )

    # 10. Place order
    order_result = await schwab_place_option_order(
        symbol=option_symbol,
        quantity=quantity,
        side="buy_to_open",
        order_type="LIMIT",
        price=limit_price,
    )

    result["order"] = order_result
    if order_result.get("status") == "submitted":
        result["action"] = "buy_to_open"
        result["reason"] = f"Placed {quantity}x {option_symbol} @ ${limit_price}"
        initialize_position(
            {
                "option_symbol": option_symbol,
                "asset_type": "OPTION",
                "quantity": quantity,
                "average_price": limit_price,
                "underlying": SYMBOL,
            },
            brain_metadata={
                "score": signal["confidence"],
                "hold_guidance": "swing" if swing_mode else "scalp",
                "momentum_assessment": "strong" if signal["confidence"] >= 80 else "moderate",
                "thesis": signal["reason"],
            },
            trend_mode=trend_mode,
        )
        # Notify
        try:
            from tools.delivery import send_telegram
            msg = (
                f"📈 *QQQ VWAP Bounce Entry*\n"
                f"CALL {atm_strike}\n"
                f"Qty: {quantity} | Limit: ${limit_price}\n"
                f"VWAP: {signal['vwap']} | Price: {signal['price']}"
            )
            import asyncio
            asyncio.create_task(send_telegram(message=msg))
        except Exception:
            pass
    else:
        result["reason"] = f"Order failed: {order_result.get('error', order_result)}"
        logger.error(result["reason"])

    return result
