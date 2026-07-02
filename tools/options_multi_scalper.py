"""
Multi-Symbol Options Scalper for Schwab

Cycles through SPY, QQQ, TSLA and executes the options scalper workflow
for each symbol independently. Called by the scheduler every ~2 minutes
with rotation through symbols.
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List
from loguru import logger

# Symbols to trade — matches config.yaml watchlist
OPTIONS_SYMBOLS = ["SPY", "QQQ", "TSLA"]

# Track which symbol to check next
_symbol_index = 0

# When true and today is Friday, buy Monday expiration instead of 0DTE
SWING_HOLD_ON_FRIDAY = os.getenv("OPTIONS_SWING_HOLD_ON_FRIDAY", "true").lower() == "true"


def _target_expiration_for_hold(swing_hold: bool = False, today=None) -> str:
    """Return YYYY-MM-DD expiration target."""
    if today is None:
        today = datetime.now().date()
    if swing_hold:
        # Friday -> Monday, otherwise next trading day
        if today.weekday() == 4:
            target = today + timedelta(days=3)
        else:
            target = today + timedelta(days=1)
            if target.weekday() >= 5:
                target += timedelta(days=2)
    else:
        target = today
    return target.strftime("%Y-%m-%d")


async def run_options_scalper_for_symbol(symbol: str, orchestrator=None) -> Dict:
    """Run the options scalper workflow for a single symbol."""
    from tools.schwab import schwab_check_compliance, schwab_get_positions, schwab_get_option_chain_parsed, schwab_place_option_order
    from tools.brain import reason_about_options_setup, options_risk_governor
    from tools.market_data import fetch_futures_data
    from tools.analysis import calculate_technicals
    
    logger.info(f"📈 Options scalper: evaluating {symbol}")
    
    result = {
        "symbol": symbol,
        "action": "none",
        "reason": "",
        "order_result": None,
    }
    
    try:
        # 1. Compliance check
        compliance = await schwab_check_compliance()
        if not compliance.get("can_trade", True):
            result["reason"] = f"Compliance: {compliance.get('reason')}"
            logger.warning(f"Options scalper {symbol}: {result['reason']}")
            return result
        
        # 2. Get current positions
        positions = await schwab_get_positions()
        option_positions = [p for p in positions if p.get("asset_type") == "OPTION"]
        
        # Max 2 concurrent option positions
        if len(option_positions) >= 2:
            result["reason"] = "Max 2 concurrent option positions reached"
            logger.info(f"Options scalper {symbol}: {result['reason']}")
            return result
        
        # 3. Fetch underlying data
        # CRITICAL FIX: use equity data fetcher, not futures data for SPY/QQQ/TSLA
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", interval="5m")
        if hist.empty:
            result["reason"] = "No market data"
            return result
        ohlcv_data = hist.reset_index().rename(columns={
            "Date": "timestamp", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume"
        }).to_dict("records")
        
        # 4. Calculate technicals
        technicals = calculate_technicals(ohlcv_data=ohlcv_data, indicators=["rsi_14", "sma_20"])
        
        # 5. Determine preliminary direction from recent price action so we fetch the right option chain
        latest_close = ohlcv_data[-1]["close"]
        prior_day_close = ohlcv_data[0]["close"] if len(ohlcv_data) > 100 else ohlcv_data[-20]["close"]
        preliminary_direction = "long" if latest_close >= prior_day_close else "short"
        
        # 6. Fetch option chain
        # CRITICAL FIX: pass actual direction so puts are fetched when gap is down
        option_chain = await schwab_get_option_chain_parsed(symbol, direction=preliminary_direction)
        if "error" in option_chain:
            result["reason"] = f"Option chain error: {option_chain['error']}"
            return result
        
        # 7. Brain inference
        brain_decision = await reason_about_options_setup(
            symbol=symbol,
            ohlcv_data=ohlcv_data,
            technicals=technicals,
            option_chain=option_chain,
        )
        
        direction = brain_decision.get("direction", "none")
        score = brain_decision.get("score", 0)
        
        if direction == "none" or score < 45:
            result["reason"] = f"Brain: {direction}, score {score} — no trade"
            logger.info(f"Options scalper {symbol}: {result['reason']}")
            return result
        
        # 7. Risk governor
        risk = await options_risk_governor(
            options_decision=brain_decision,
            compliance_status=compliance,
            current_positions=option_positions,
        )
        
        if not risk.get("approved", False):
            result["reason"] = f"Risk: {risk.get('reason')}"
            logger.warning(f"Options scalper {symbol}: {result['reason']}")
            return result
        
        # 8. Build option symbol
        # Format: "SPY   250620C00450000" — Schwab format
        from datetime import datetime
        expiration = brain_decision.get("expiration", "")
        strike = brain_decision.get("strike", 0)
        option_type = brain_decision.get("option_type", "call").upper()
        
        # Parse expiration to MMDD format
        try:
            exp_dt = datetime.strptime(expiration, "%Y-%m-%d")
            exp_str = exp_dt.strftime("%y%m%d")
        except Exception:
            exp_str = expiration.replace("-", "")[2:]  # Fallback
        
        # Format strike: 450.00 -> 00450000
        strike_str = f"{int(strike * 1000):08d}"
        option_symbol = f"{symbol:<6}{exp_str}{option_type[0]}{strike_str}"
        
        # 9. Determine max entry price (limit order at mid or brain's max)
        max_entry = brain_decision.get("max_entry_price", 0)
        
        # Find matching strike in chain for current price
        limit_price = max_entry
        for s in option_chain.get("strikes", []):
            if abs(s["strike"] - strike) < 0.01:
                mid = (s["bid"] + s["ask"]) / 2 if s["bid"] and s["ask"] else 0
                if mid > 0:
                    limit_price = round(min(mid, max_entry) if max_entry > 0 else mid, 2)
                break
        
        if limit_price <= 0:
            result["reason"] = "Could not determine limit price"
            return result
        
        # 10. Determine quantity based on confidence + momentum
        # Base: 2 contracts | Boost: 4 contracts on high-conviction runners
        momentum = brain_decision.get("momentum_assessment", "moderate")
        if score >= 70 and momentum == "strong":
            quantity = 4
        elif score >= 55:
            quantity = 3
        else:
            quantity = 2
        
        # Enforce max position cost from risk governor ($1000 default)
        max_cost = risk.get("max_position_cost", 1000)
        estimated_cost = limit_price * 100 * quantity
        if estimated_cost > max_cost:
            # Scale down to fit under cap
            quantity = max(1, int(max_cost / (limit_price * 100)))
            logger.info(f"Scaled down quantity to {quantity} to stay under ${max_cost} cap")
        
        side = "buy_to_open"
        order_type = "LIMIT"
        
        order_result = await schwab_place_option_order(
            symbol=option_symbol,
            quantity=quantity,
            side=side,
            order_type=order_type,
            price=limit_price,
        )
        
        result["action"] = "buy_to_open"
        result["order_result"] = order_result
        result["reason"] = f"Placed {side} {quantity}x {option_symbol} @ {limit_price}"
        
        # Initialize position state with brain metadata for profit-locking engine
        if order_result.get("status") == "submitted":
            from tools.profit_locking_engine import initialize_position
            brain_meta = {
                "score": score,
                "hold_guidance": brain_decision.get("hold_guidance", "partial_then_ride"),
                "momentum_assessment": brain_decision.get("momentum_assessment", "moderate"),
                "thesis": brain_decision.get("thesis", ""),
            }
            initialize_position({
                "option_symbol": option_symbol,
                "asset_type": "OPTION",
                "quantity": quantity,
                "average_price": limit_price,
                "underlying": symbol,
            }, brain_metadata=brain_meta, trend_mode="scalp")
        
        # Notify
        from tools.delivery import send_telegram
        hold = brain_decision.get("hold_guidance", "partial_then_ride")
        momentum = brain_decision.get("momentum_assessment", "moderate")
        msg = f"📈 *Options Entry: {symbol}*\n"
        msg += f"*{option_type} {direction.upper()}* {strike}\n"
        msg += f"*Qty:* {quantity} contract(s)\n"
        msg += f"*Limit:* ${limit_price}\n"
        msg += f"*Score:* {score}/100 | *Hold:* {hold} | *Momentum:* {momentum}"
        import asyncio
        asyncio.create_task(send_telegram(message=msg))
        
        logger.info(f"Options scalper {symbol}: {result['reason']} | hold={hold} momentum={momentum}")
        
    except Exception as e:
        logger.error(f"Options scalper {symbol} error: {e}")
        result["reason"] = f"Error: {str(e)}"
    
    return result


async def run_options_scalper_rotating(orchestrator=None) -> Dict:
    """
    Run the options scalper for the next symbol in rotation.
    Called by scheduler every 2 minutes to cycle through SPY → QQQ → TSLA.
    """
    global _symbol_index
    
    symbol = OPTIONS_SYMBOLS[_symbol_index % len(OPTIONS_SYMBOLS)]
    _symbol_index += 1
    
    result = await run_options_scalper_for_symbol(symbol, orchestrator)
    
    # Log rotation
    next_symbol = OPTIONS_SYMBOLS[_symbol_index % len(OPTIONS_SYMBOLS)]
    logger.info(f"Options scalper rotation: next symbol = {next_symbol}")
    
    return result


# ─── PRE-MARKET GAP ENTRY ───
# Fires at 9:28 AM ET, every trading day. Analyzes overnight gap for
# SPY / QQQ / TSLA and places 0DTE option orders queued for the 9:30 open.

_GAP_SYMBOLS = ["SPY", "QQQ", "TSLA"]
_MIN_GAP_PCT = 0.30          # Minimum gap % to trigger an entry
_MAX_GAP_PCT = 8.0           # Skip if gap is absurd (likely halt/gap risk)
_GAP_BOOST_THRESHOLD = 1.5   # Gap > 1.5% gets max size


def _fetch_gap_data(symbol: str) -> Dict:
    """Fetch prior close and pre-market price for gap calculation."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", interval="1d")
        if len(hist) < 2:
            return {"gap_pct": 0.0, "prior_close": 0.0, "current": 0.0}
        
        prior_close = float(hist["Close"].iloc[-2])
        
        # Try pre-market / current price
        try:
            fast = ticker.history(period="1d", interval="1m")
            current = float(fast["Close"].iloc[-1]) if len(fast) > 0 else prior_close
        except Exception:
            current = prior_close
        
        gap_pct = ((current - prior_close) / prior_close) * 100 if prior_close else 0.0
        return {
            "gap_pct": round(gap_pct, 2),
            "prior_close": round(prior_close, 2),
            "current": round(current, 2),
        }
    except Exception as e:
        logger.warning(f"Gap data fetch failed for {symbol}: {e}")
        return {"gap_pct": 0.0, "prior_close": 0.0, "current": 0.0}


def _fetch_premarket_intraday(symbol: str) -> List[Dict]:
    """Fetch today's 1-minute candles (includes premarket/regular hours)."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="1m")
        if hist.empty:
            return []
        df = hist.reset_index().rename(columns={
            "Datetime": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })
        return df.to_dict("records")
    except Exception as e:
        logger.warning(f"Intraday premarket fetch failed for {symbol}: {e}")
        return []


# ─── BB/VWAP/VOLUME REVERSAL CRITERION CONFIG ───
# Env flags so you can enable/tune without code changes:
#   PREMARKET_REVERSAL_ENABLED=true
#   PREMARKET_REVERSAL_MODE=confirm|filter|fade   (default: confirm)
#   PREMARKET_REVERSAL_MIN_VOLUME_RATIO=1.0
#   REVERSAL_STRATEGY=mean_reversion|breakout|both (default: both)
_PREMARKET_REVERSAL_ENABLED = (
    os.getenv("PREMARKET_REVERSAL_ENABLED", "false").lower() == "true"
)
_PREMARKET_REVERSAL_MODE = os.getenv("PREMARKET_REVERSAL_MODE", "confirm").lower()
_PREMARKET_REVERSAL_MIN_VOLUME_RATIO = float(
    os.getenv("PREMARKET_REVERSAL_MIN_VOLUME_RATIO", "1.0")
)
_REVERSAL_STRATEGY = os.getenv("REVERSAL_STRATEGY", "mean_reversion").lower()


def _gap_to_direction(gap_pct: float) -> str:
    """Simple directional bias from gap."""
    if gap_pct >= _MIN_GAP_PCT:
        return "long"
    elif gap_pct <= -_MIN_GAP_PCT:
        return "short"
    return "none"


def _gap_to_score(gap_pct: float) -> int:
    """Score purely from gap magnitude and direction conviction."""
    abs_gap = abs(gap_pct)
    if abs_gap < _MIN_GAP_PCT:
        return 0
    if abs_gap > _MAX_GAP_PCT:
        return 0  # Too violent — skip
    # Score 40-80 based on gap size
    base = 40
    bonus = min(int((abs_gap - _MIN_GAP_PCT) * 15), 40)
    return base + bonus


def _gap_to_contracts(gap_pct: float) -> int:
    """Size based on gap magnitude."""
    abs_gap = abs(gap_pct)
    if abs_gap >= _GAP_BOOST_THRESHOLD:
        return 4
    elif abs_gap >= 0.8:
        return 3
    else:
        return 2


async def run_premarket_gap_entry(orchestrator=None) -> Dict:
    """
    Pre-market gap entry — runs once at 9:28 AM ET.
    Places 0DTE option orders for the 9:30 AM open.
    """
    from tools.schwab import schwab_check_compliance, schwab_get_positions, schwab_get_option_chain_parsed, schwab_place_option_order
    from tools.profit_locking_engine import initialize_position
    
    logger.info("📈 PRE-MARKET GAP ENTRY: analyzing overnight gaps")
    
    # 0. TREND DETECTION — decides scalp vs trend mode
    from tools.trend_detector import detect_market_trend
    trend = detect_market_trend()
    base_trend_mode = trend.get("trend_mode", "scalp")
    swing_mode = SWING_HOLD_ON_FRIDAY and datetime.now().weekday() == 4
    trend_mode = "weekend_hold" if swing_mode else base_trend_mode
    logger.info(f"📊 TREND DETECTOR: {trend['recommendation']} | mode={trend_mode}")
    
    # 1. Compliance check
    compliance = await schwab_check_compliance()
    if not compliance.get("can_trade", True):
        logger.warning("Pre-market entry blocked: compliance check failed")
        return {"action": "none", "reason": "Compliance failed"}
    
    positions = await schwab_get_positions()
    option_positions = [p for p in positions if p.get("asset_type") == "OPTION"]
    
    # 2. Evaluate each symbol
    entries = []
    for symbol in _GAP_SYMBOLS:
        gap_data = _fetch_gap_data(symbol)
        gap_pct = gap_data["gap_pct"]
        direction = _gap_to_direction(gap_pct)
        score = _gap_to_score(gap_pct)
        
        if direction == "none" or score < 40:
            logger.info(f"Pre-market {symbol}: gap {gap_pct:+.2f}% | score {score} | NO ENTRY")
            continue
        
        # 3. BB/VWAP/VOLUME REVERSAL CRITERION (new)
        reversal_info = None
        if _PREMARKET_REVERSAL_ENABLED:
            from tools.analysis import analyze_premarket_reversal_setup
            intraday = _fetch_premarket_intraday(symbol)
            reversal_info = analyze_premarket_reversal_setup(
                intraday,
                min_volume_ratio=_PREMARKET_REVERSAL_MIN_VOLUME_RATIO,
                strategy=_REVERSAL_STRATEGY,
            )
            rev_signal = reversal_info.get("signal", "neutral")
            rev_strength = reversal_info.get("strength", 0.0)
            rev_direction = reversal_info.get("direction", "none")
            rev_modifier = reversal_info.get("score_modifier", 0)
            
            # Align modifier to the gap direction trade
            if direction == "long":
                gap_aligned_modifier = rev_modifier
            elif direction == "short":
                gap_aligned_modifier = -rev_modifier
            else:
                gap_aligned_modifier = 0
            
            logger.info(
                f"Pre-market {symbol}: reversal={rev_signal} "
                f"direction={rev_direction} strength={rev_strength} "
                f"modifier={rev_modifier} aligned={gap_aligned_modifier}"
            )
            
            if _PREMARKET_REVERSAL_MODE == "filter":
                # Skip trades where a strong reversal signal conflicts with the gap
                if (
                    rev_direction != "none"
                    and rev_direction != direction
                    and rev_strength >= 0.5
                ):
                    logger.info(
                        f"Pre-market {symbol}: reversal signal conflicts with gap direction, skipping"
                    )
                    continue
            elif _PREMARKET_REVERSAL_MODE == "fade":
                # Flip direction on a strong reversal read (mean-reversion / fade the gap)
                if (
                    rev_direction != "none"
                    and rev_direction != direction
                    and rev_strength >= 0.7
                ):
                    old_direction = direction
                    direction = rev_direction
                    option_type = "CALL" if direction == "long" else "PUT"
                    gap_pct = -gap_pct  # invert gap for sizing/scoring context
                    logger.info(
                        f"Pre-market {symbol}: FADING gap — {old_direction} -> {direction}"
                    )
            
            # In all modes, apply the aligned modifier to the score (capped 0-100)
            score = max(0, min(100, score + gap_aligned_modifier))
        
        # Re-check score floor after reversal adjustment
        if direction == "none" or score < 40:
            logger.info(
                f"Pre-market {symbol}: gap {gap_pct:+.2f}% | post-reversal score {score} | NO ENTRY"
            )
            continue
        
        # 4. Get option chain (0DTE or next expiration for weekend hold)
        target_exp = _target_expiration_for_hold(swing_mode)
        option_chain = await schwab_get_option_chain_parsed(symbol, direction=direction, expiration=target_exp)
        if "error" in option_chain:
            logger.warning(f"Pre-market {symbol}: option chain error: {option_chain['error']}")
            continue
        
        # 4. Pick ATM strike
        expiration = option_chain.get("expiration", datetime.now().strftime("%Y-%m-%d"))
        strikes = option_chain.get("strikes", [])
        # Use option chain underlying price (Schwab) — more accurate than yfinance pre-market
        underlying_price = option_chain.get("underlying_price", gap_data["current"])
        
        if underlying_price <= 0:
            logger.error(f"Pre-market {symbol}: underlying_price is 0 — cannot select strike")
            continue
        
        logger.info(f"Pre-market {symbol}: underlying_price={underlying_price}, {len(strikes)} strikes available")
        
        # Find ATM strike
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
            logger.warning(f"Pre-market {symbol}: no ATM strike found (underlying={underlying_price})")
            continue
        
        # Determine option type
        option_type = "CALL" if direction == "long" else "PUT"
        
        # Build option symbol: SPY   250609C00739000
        exp_dt = datetime.strptime(expiration, "%Y-%m-%d")
        exp_str = exp_dt.strftime("%y%m%d")
        strike_str = f"{int(atm_strike * 1000):08d}"
        option_symbol = f"{symbol:<6}{exp_str}{option_type[0]}{strike_str}"
        
        # 5. Determine limit price — NEVER pay above ask
        bid = atm_data.get("bid", 0)
        ask = atm_data.get("ask", 0)
        if bid and ask:
            # CRITICAL FIX: use mid-price, never above ask
            spread = ask - bid
            mid = round(bid + spread * 0.5, 2)
            limit_price = min(mid, ask)  # Never above ask
        else:
            limit_price = round(atm_data.get("last", atm_strike * 0.01), 2)
        
        if limit_price <= 0:
            logger.warning(f"Pre-market {symbol}: invalid limit price {limit_price}")
            continue
        
        # 6. Determine quantity
        quantity = _gap_to_contracts(gap_pct)
        max_cost = compliance.get("buying_power", 4000)
        estimated_cost = limit_price * 100 * quantity
        if estimated_cost > max_cost * 0.25:  # Keep under 25% of BP per trade
            quantity = max(1, int((max_cost * 0.25) / (limit_price * 100)))
        
        # Max 2 concurrent option positions total
        if len(option_positions) + len(entries) >= 2:
            logger.info(f"Pre-market {symbol}: max 2 positions reached, skipping")
            continue
        
        # 7. Idempotency check — don't duplicate a 0DTE order for this symbol/strike today
        from tools.schwab import get_schwab_client
        client = get_schwab_client()
        account_hash = (await client.get_account_numbers())[0]
        import datetime as _dt
        today_start = _dt.datetime.combine(_dt.date.today(), _dt.time.min)
        existing_orders = client.client.get_orders_for_account(
            account_hash,
            from_entered_datetime=today_start,
            to_entered_datetime=_dt.datetime.now()
        ).json()
        already_ordered = any(
            o['orderLegCollection'][0]['instrument']['symbol'] == option_symbol
            and o['orderLegCollection'][0]['instruction'] == 'BUY_TO_OPEN'
            and o['status'] in ('WORKING', 'FILLED', 'ACCEPTED', 'QUEUED', 'PENDING_ACTIVATION')
            for o in existing_orders
        )
        if already_ordered:
            logger.info(f"Pre-market {symbol}: order for {option_symbol} already exists today, skipping")
            continue
        
        # 8. Place order
        logger.info(
            f"📈 PRE-MARKET ENTRY: {symbol} {direction.upper()} | "
            f"gap {gap_pct:+.2f}% | {option_type} {atm_strike} | "
            f"qty {quantity} @ limit ${limit_price}"
        )
        
        order_result = await schwab_place_option_order(
            symbol=option_symbol,
            quantity=quantity,
            side="buy_to_open",
            order_type="LIMIT",
            price=limit_price,
        )
        
        if order_result.get("status") == "submitted":
            # Initialize profit-locking state
            thesis = f"Pre-market gap entry: {gap_pct:+.2f}% on {symbol}"
            if _PREMARKET_REVERSAL_ENABLED and reversal_info:
                thesis += (
                    f" | reversal={reversal_info.get('signal')} "
                    f"strength={reversal_info.get('strength')} "
                    f"vol_ratio={reversal_info.get('volume_ratio')}"
                )
            brain_meta = {
                "score": score,
                "hold_guidance": "partial_then_ride" if gap_pct >= 1.0 else "scalp",
                "momentum_assessment": "strong" if abs(gap_pct) >= 1.0 else "moderate",
                "thesis": thesis,
            }
            initialize_position({
                "option_symbol": option_symbol,
                "asset_type": "OPTION",
                "quantity": quantity,
                "average_price": limit_price,
                "underlying": symbol,
            }, brain_metadata=brain_meta, trend_mode=trend_mode)
            
            entry_record = {
                "symbol": symbol,
                "direction": direction,
                "option_type": option_type,
                "strike": atm_strike,
                "quantity": quantity,
                "limit_price": limit_price,
                "gap_pct": gap_pct,
                "score": score,
                "order_id": order_result.get("order_id"),
            }
            if _PREMARKET_REVERSAL_ENABLED and reversal_info:
                entry_record["reversal"] = {
                    "signal": reversal_info.get("signal"),
                    "direction": reversal_info.get("direction"),
                    "strength": reversal_info.get("strength"),
                    "volume_ratio": reversal_info.get("volume_ratio"),
                    "vwap": reversal_info.get("vwap"),
                    "bb_bands": reversal_info.get("bb_bands"),
                    "reasons": reversal_info.get("reasons"),
                }
            entries.append(entry_record)
            option_positions.append({"asset_type": "OPTION"})  # Count it
            
            # Notify
            from tools.delivery import send_telegram
            reversal_tag = ""
            if _PREMARKET_REVERSAL_ENABLED and reversal_info:
                rev_signal = reversal_info.get("signal", "neutral")
                rev_strength = reversal_info.get("strength", 0.0)
                reversal_tag = f" | Reversal: {rev_signal} ({rev_strength})"
            msg = (
                f"📈 *Pre-Market Gap Entry: {symbol}*\n"
                f"*{option_type} {direction.upper()}* {atm_strike}\n"
                f"*Gap:* {gap_pct:+.2f}%\n"
                f"*Qty:* {quantity} | *Limit:* ${limit_price}\n"
                f"*Score:* {score}/100{reversal_tag}"
            )
            import asyncio
            asyncio.create_task(send_telegram(message=msg))
        else:
            logger.error(f"Pre-market {symbol}: order failed — {order_result}")
    
    logger.info(f"Pre-market gap entry complete: {len(entries)} order(s) placed")
    return {
        "action": "entry" if entries else "none",
        "entries": entries,
        "count": len(entries),
    }
