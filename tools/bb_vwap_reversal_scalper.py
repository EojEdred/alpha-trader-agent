"""
Continuous BB/VWAP/Volume Reversal Scalper

Intraday mean-reversion strategy for Schwab options on SPY, QQQ, TSLA.
Watches 1-minute price vs Bollinger Bands + VWAP, confirmed by volume.
When price pushes outside the BB envelope on elevated volume, it expects a
mean-reversion and buys a 0DTE option in the reversal direction.

Runs every 2 minutes during equity market hours.
"""

import os
from datetime import datetime
from typing import Dict, List
from loguru import logger

from tools.options_multi_scalper import _target_expiration_for_hold, SWING_HOLD_ON_FRIDAY

# Symbols to scan for reversal setups
REVERSAL_SYMBOLS = ["SPY", "QQQ", "TSLA"]

# Entry thresholds
_MIN_REVERSAL_STRENGTH = float(os.getenv("REVERSAL_MIN_STRENGTH", "0.7"))
_MIN_VOLUME_RATIO = float(os.getenv("REVERSAL_MIN_VOLUME_RATIO", "1.0"))
_REVERSAL_STRATEGY = os.getenv("REVERSAL_STRATEGY", "mean_reversion").lower()
_REVERSAL_TIMEFRAME = os.getenv("REVERSAL_TIMEFRAME", "1m").lower()
_MAX_POSITIONS = 2

# Track last signal time per symbol to avoid duplicate entries
_last_signal_time: Dict[str, datetime] = {}


def _fetch_data(symbol: str) -> List[Dict]:
    """Fetch OHLCV from Yahoo Finance using the configured REVERSAL_TIMEFRAME."""
    interval = _REVERSAL_TIMEFRAME
    # yfinance interval -> period mapping with enough history for a 20-bar BB
    period_map = {
        "1m": "1d",
        "2m": "5d",
        "5m": "5d",
        "15m": "5d",
        "30m": "1mo",
        "60m": "1mo",
        "1h": "20d",
        "90m": "1mo",
        "1d": "3mo",
    }
    period = period_map.get(interval, "1d")
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval, prepost=True)
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
        logger.warning(f"BB/VWAP reversal scalper: failed to fetch {interval} data for {symbol}: {e}")
        return []


def _detect_reversal_setup(candles: List[Dict]) -> Dict:
    """
    Detect oversold/overbought mean-reversion setup using BB/VWAP/volume.
    Mirrors the logic in tools.analysis.analyze_premarket_reversal_setup but
    tuned for live intraday trading.
    """
    from tools.analysis import analyze_premarket_reversal_setup

    result = analyze_premarket_reversal_setup(
        candles,
        bb_window=20,
        bb_devs=[1.0, 2.0, 3.0],
        volume_lookback=20,
        min_volume_ratio=_MIN_VOLUME_RATIO,
        strategy=_REVERSAL_STRATEGY,
    )

    # Flatten np.float64 for JSON/telegram
    for key in ["vwap", "bb_middle", "volume_ratio", "last_close", "strength", "score_modifier"]:
        if key in result and result[key] is not None:
            result[key] = float(result[key])
    if "bb_bands" in result:
        result["bb_bands"] = {k: float(v) for k, v in result["bb_bands"].items()}

    return result


async def _place_reversal_trade(
    symbol: str,
    direction: str,
    reversal: Dict,
    compliance: Dict,
    option_positions: List[Dict],
) -> Dict:
    """Place a 0DTE option trade in the reversal direction."""
    from tools.schwab import schwab_get_option_chain_parsed, schwab_place_option_order
    from tools.profit_locking_engine import initialize_position

    result = {"action": "none", "reason": "", "order": None}

    swing_mode = SWING_HOLD_ON_FRIDAY and datetime.now().weekday() == 4
    target_exp = _target_expiration_for_hold(swing_mode)
    trend_mode = "weekend_hold" if swing_mode else "scalp"

    option_chain = await schwab_get_option_chain_parsed(symbol, direction=direction, expiration=target_exp)
    if "error" in option_chain:
        result["reason"] = f"Option chain error: {option_chain['error']}"
        logger.warning(result["reason"])
        return result

    underlying_price = option_chain.get("underlying_price", reversal.get("last_close", 0))
    strikes = option_chain.get("strikes", [])
    if not strikes:
        result["reason"] = "No strikes returned"
        return result

    # Pick ATM strike
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

    option_type = "CALL" if direction == "long" else "PUT"
    expiration = option_chain.get("expiration", datetime.now().strftime("%Y-%m-%d"))
    exp_str = datetime.strptime(expiration, "%Y-%m-%d").strftime("%y%m%d")
    strike_str = f"{int(atm_strike * 1000):08d}"
    option_symbol = f"{symbol:<6}{exp_str}{option_type[0]}{strike_str}"

    # Limit price at mid, never above ask
    bid = atm_data.get("bid", 0)
    ask = atm_data.get("ask", 0)
    if bid and ask:
        limit_price = round(bid + (ask - bid) * 0.5, 2)
        limit_price = min(limit_price, ask)
    else:
        limit_price = round(atm_data.get("last", atm_strike * 0.01), 2)

    if limit_price <= 0:
        result["reason"] = f"Invalid limit price {limit_price}"
        return result

    # Quantity: 2 contracts default, scaled by buying power
    quantity = 2
    max_cost = compliance.get("buying_power", 4000)
    estimated_cost = limit_price * 100 * quantity
    if estimated_cost > max_cost * 0.25:
        quantity = max(1, int((max_cost * 0.25) / (limit_price * 100)))

    # Place order
    logger.info(
        f"📈 REVERSAL ENTRY: {symbol} {direction.upper()} | {option_type} {atm_strike} | "
        f"signal={reversal.get('signal')} strength={reversal.get('strength')} "
        f"vol_ratio={reversal.get('volume_ratio')} | qty={quantity} @ ${limit_price}"
    )

    order_result = await schwab_place_option_order(
        symbol=option_symbol,
        quantity=quantity,
        side="buy_to_open",
        order_type="LIMIT",
        price=limit_price,
    )

    if order_result.get("status") == "submitted":
        brain_meta = {
            "score": 70 + int(reversal.get("strength", 0) * 30),
            "hold_guidance": "scalp",
            "momentum_assessment": "strong" if reversal.get("strength", 0) >= 0.9 else "moderate",
            "thesis": (
                f"BB/VWAP reversal: {reversal.get('signal')} on {symbol} "
                f"strength={reversal.get('strength')} vol_ratio={reversal.get('volume_ratio')}"
            ),
        }
        initialize_position({
            "option_symbol": option_symbol,
            "asset_type": "OPTION",
            "quantity": quantity,
            "average_price": limit_price,
            "underlying": symbol,
        }, brain_metadata=brain_meta, trend_mode=trend_mode)

        result["action"] = "buy_to_open"
        result["order"] = order_result
        result["reason"] = f"Submitted {option_symbol}"

        # Telegram alert
        from tools.delivery import send_telegram
        msg = (
            f"📈 *BB/VWAP Reversal Entry: {symbol}*\n"
            f"*{option_type} {direction.upper()}* {atm_strike}\n"
            f"*Signal:* {reversal.get('signal')} (strength {reversal.get('strength')})\n"
            f"*VWAP:* ${reversal.get('vwap')} | *VolRatio:* {reversal.get('volume_ratio')}x\n"
            f"*Qty:* {quantity} | *Limit:* ${limit_price}"
        )
        import asyncio
        asyncio.create_task(send_telegram(message=msg))
    else:
        result["reason"] = f"Order failed: {order_result}"
        logger.error(result["reason"])

    return result


async def run_bb_vwap_reversal_scalper(orchestrator=None) -> Dict:
    """
    Main entry point: scan SPY/QQQ/TSLA for BB/VWAP/volume reversal setups
    and enter 0DTE option trades in CONFIRM mode.
    """
    from tools.schwab import schwab_check_compliance, schwab_get_positions

    result = {"action": "scan", "symbols": {}, "entries": [], "errors": []}

    # Market hours sanity check (ET)
    try:
        import pytz
        et = pytz.timezone("America/New_York")
        now = datetime.now(et)
        if now.weekday() >= 5 or now.hour < 9 or (now.hour == 9 and now.minute < 30) or now.hour >= 16:
            result["reason"] = "Outside equity market hours"
            logger.info(f"BB/VWAP reversal scalper: {result['reason']}")
            return result
    except Exception:
        pass

    # Compliance
    compliance = await schwab_check_compliance()
    if not compliance.get("can_trade", True):
        result["reason"] = f"Compliance: {compliance.get('reason')}"
        logger.warning(f"BB/VWAP reversal scalper: {result['reason']}")
        return result

    # Positions
    positions = await schwab_get_positions()
    option_positions = [p for p in positions if p.get("asset_type") == "OPTION"]

    for symbol in REVERSAL_SYMBOLS:
        try:
            candles = _fetch_data(symbol)
            if len(candles) < 25:
                result["symbols"][symbol] = {"signal": "none", "reason": "not enough data"}
                continue

            reversal = _detect_reversal_setup(candles)
            rev_signal = reversal.get("signal", "neutral")
            rev_strength = reversal.get("strength", 0.0)
            rev_direction = reversal.get("direction", "none")

            result["symbols"][symbol] = {
                "signal": rev_signal,
                "direction": rev_direction,
                "strength": rev_strength,
                "volume_ratio": reversal.get("volume_ratio"),
                "vwap": reversal.get("vwap"),
            }

            logger.info(
                f"BB/VWAP reversal scalper {symbol}: {rev_signal} "
                f"direction={rev_direction} strength={rev_strength} "
                f"vol_ratio={reversal.get('volume_ratio')}"
            )

            # Entry conditions
            if rev_direction == "none" or rev_strength < _MIN_REVERSAL_STRENGTH:
                continue

            # Position limits
            if len(option_positions) >= _MAX_POSITIONS:
                logger.info(f"BB/VWAP reversal scalper {symbol}: max {_MAX_POSITIONS} positions reached")
                continue

            # Avoid duplicate signal within 15 minutes for same symbol/direction
            sig_key = f"{symbol}:{rev_direction}"
            last_time = _last_signal_time.get(sig_key)
            if last_time and (datetime.now() - last_time).total_seconds() < 900:
                logger.info(f"BB/VWAP reversal scalper {symbol}: duplicate signal suppressed")
                continue

            trade = await _place_reversal_trade(symbol, rev_direction, reversal, compliance, option_positions)
            if trade.get("action") == "buy_to_open":
                _last_signal_time[sig_key] = datetime.now()
                result["entries"].append({"symbol": symbol, "direction": rev_direction, "order": trade["order"]})
                option_positions.append({"asset_type": "OPTION"})  # count it

        except Exception as e:
            logger.error(f"BB/VWAP reversal scalper {symbol} error: {e}")
            result["errors"].append({"symbol": symbol, "error": str(e)})

    result["count"] = len(result["entries"])
    return result
