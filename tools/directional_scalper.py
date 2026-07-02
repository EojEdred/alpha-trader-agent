"""
Directional Options Scalper — 2 to 12 DTE, ATM only.

Trades SPY/QQQ/TSLA directional options with tight risk management.
- Uses gap/momentum for direction
- Picks ATM strike for max delta, less decay drag
- 2-12 DTE for balance of gamma and time
- Hard stop and profit target on every trade
"""

import asyncio
from datetime import date, timedelta, datetime
from typing import Dict, List
from loguru import logger

SYMBOLS = ["SPY", "QQQ", "TSLA"]
MIN_GAP_PCT = 0.30
MAX_GAP_PCT = 6.0
MIN_SCORE = 40
MAX_RISK_DOLLARS = 100
MAX_POSITIONS = 1
MIN_DTE = 2
MAX_DTE = 12
TARGET_DELTA_MIN = 0.45
TARGET_DELTA_MAX = 0.60


def _build_option_symbol(underlying: str, expiration: date, strike: float, option_type: str) -> str:
    exp_str = expiration.strftime("%y%m%d")
    letter = option_type[0].upper()
    strike_str = f"{int(strike * 1000):08d}"
    return f"{underlying:<6}{exp_str}{letter}{strike_str}"


def _gap_to_direction(gap_pct: float) -> str:
    if gap_pct >= MIN_GAP_PCT:
        return "long"
    elif gap_pct <= -MIN_GAP_PCT:
        return "short"
    return "none"


def _gap_to_score(gap_pct: float) -> int:
    abs_gap = abs(gap_pct)
    if abs_gap < MIN_GAP_PCT:
        return 0
    if abs_gap > MAX_GAP_PCT:
        return 0
    base = 40
    bonus = min(int((abs_gap - MIN_GAP_PCT) * 12), 35)
    return base + bonus


def _fetch_gap_data(symbol: str) -> Dict:
    """Fetch prior day close and current price for gap calc."""
    import yfinance as yf
    try:
        ticker = yf.Ticker(symbol)
        daily = ticker.history(period="5d", interval="1d")
        if daily.empty or len(daily) < 2:
            return {"gap_pct": 0.0, "prior_close": 0.0, "current": 0.0}
        prior_close = float(daily["Close"].iloc[-2])
        intraday = ticker.history(period="1d", interval="5m")
        current = float(intraday["Close"].iloc[-1]) if not intraday.empty else float(daily["Close"].iloc[-1])
        gap_pct = ((current - prior_close) / prior_close) * 100 if prior_close else 0.0
        return {
            "gap_pct": round(gap_pct, 2),
            "prior_close": round(prior_close, 2),
            "current": round(current, 2),
        }
    except Exception as e:
        logger.error(f"Gap data error for {symbol}: {e}")
        return {"gap_pct": 0.0, "prior_close": 0.0, "current": 0.0}


async def _get_option_chain_for_dte(symbol: str, direction: str, dte: int):
    """Fetch option chain for a specific DTE."""
    from tools.schwab import SchwabClient
    client = SchwabClient()
    expiration = date.today() + timedelta(days=dte)
    opt_type = client.client.Options.ContractType.CALL if direction == "long" else client.client.Options.ContractType.PUT
    try:
        resp = client.client.get_option_chain(
            symbol,
            contract_type=opt_type,
            from_date=expiration,
            to_date=expiration
        )
        data = resp.json()
        exp_map = data.get('callExpDateMap' if direction == "long" else 'putExpDateMap', {})
        if not exp_map:
            return None
        exp_key = sorted(exp_map.keys())[0]
        actual_exp = datetime.strptime(exp_key.split(':')[0], "%Y-%m-%d").date()
        underlying = float(data.get('underlyingPrice', 0))
        return {
            "expiration": actual_exp,
            "underlying": underlying,
            "strikes_data": exp_map[exp_key]
        }
    except Exception as e:
        logger.debug(f"No chain for {symbol} {dte}DTE: {e}")
        return None


async def find_directional_setups() -> List[Dict]:
    """Find all 2-12 DTE directional setups at ATM."""
    setups = []
    
    for symbol in SYMBOLS:
        gap_data = _fetch_gap_data(symbol)
        gap_pct = gap_data["gap_pct"]
        direction = _gap_to_direction(gap_pct)
        score = _gap_to_score(gap_pct)
        
        if direction == "none" or score < MIN_SCORE:
            continue
        
        best_setup = None
        
        for dte in range(MIN_DTE, MAX_DTE + 1):
            chain = await _get_option_chain_for_dte(symbol, direction, dte)
            if not chain:
                continue
            
            underlying = chain["underlying"]
            strikes_data = chain["strikes_data"]
            
            # Find ATM strike with delta in target range
            best_strike = None
            best_key = None
            best_delta_diff = float('inf')
            
            for k, v in strikes_data.items():
                s = float(k)
                opt = v[0]
                delta = abs(float(opt.get('delta', 0)))
                target_delta = 0.50
                delta_diff = abs(delta - target_delta)
                
                if TARGET_DELTA_MIN <= delta <= TARGET_DELTA_MAX:
                    if delta_diff < best_delta_diff:
                        best_delta_diff = delta_diff
                        best_strike = s
                        best_key = k
            
            if not best_key:
                continue
            
            opt = strikes_data[best_key][0]
            bid = float(opt.get('bid', 0))
            ask = float(opt.get('ask', 0))
            mid = round((bid + ask) / 2, 2)
            delta = float(opt.get('delta', 0))
            option_type = "CALL" if direction == "long" else "PUT"
            option_symbol = _build_option_symbol(symbol, chain["expiration"], best_strike, option_type)
            
            stop_price = round(mid * 0.75, 2)  # 25% stop
            target_price = round(mid * 1.35, 2)  # 35% target
            risk_per_contract = round((mid - stop_price) * 100, 2)
            
            candidate = {
                "symbol": symbol,
                "direction": direction,
                "option_type": option_type,
                "option_symbol": option_symbol,
                "strike": best_strike,
                "expiration": chain["expiration"].isoformat(),
                "dte": dte,
                "underlying_price": underlying,
                "gap_pct": gap_pct,
                "score": score,
                "mid": mid,
                "bid": bid,
                "ask": ask,
                "delta": delta,
                "stop_price": stop_price,
                "target_price": target_price,
                "risk_per_contract": risk_per_contract,
            }
            
            # Prefer lower DTE among good candidates
            if best_setup is None or dte < best_setup["dte"]:
                best_setup = candidate
        
        if best_setup:
            setups.append(best_setup)
    
    setups.sort(key=lambda x: x['score'], reverse=True)
    return setups


async def enter_best_directional(max_risk: float = MAX_RISK_DOLLARS) -> Dict:
    """Enter the best directional setup if criteria met."""
    from tools.schwab import schwab_get_positions, schwab_place_option_order, schwab_check_compliance
    
    compliance = await schwab_check_compliance()
    if not compliance.get("can_trade", True):
        return {"action": "none", "reason": compliance.get("reason")}
    
    positions = await schwab_get_positions()
    option_positions = [p for p in positions if p.get("asset_type") == "OPTION"]
    if len(option_positions) >= MAX_POSITIONS:
        return {"action": "none", "reason": f"Max {MAX_POSITIONS} option position(s) open"}
    
    setups = await find_directional_setups()
    if not setups:
        return {"action": "none", "reason": "No directional setups found"}
    
    best = setups[0]
    buying_power = compliance.get("buying_power", 0)
    max_by_risk = max(1, int(max_risk / best['risk_per_contract'])) if best['risk_per_contract'] > 0 else 1
    max_by_bp = max(1, int(buying_power * 0.30 / (best['mid'] * 100)))
    quantity = min(max_by_risk, max_by_bp, 2)
    
    result = await schwab_place_option_order(
        symbol=best['option_symbol'],
        quantity=quantity,
        side="buy_to_open",
        order_type="LIMIT",
        price=best['mid']
    )
    
    if result.get('status') == 'submitted':
        return {"action": "entered", "setup": best, "quantity": quantity, "order": result}
    else:
        return {"action": "failed", "setup": best, "error": result.get('error')}


if __name__ == "__main__":
    setups = asyncio.run(find_directional_setups())
    for s in setups:
        print(f"{s['symbol']} {s['dte']}DTE {s['option_type']} | {s['option_symbol']} | "
              f"strike=${s['strike']} | mid=${s['mid']} | delta={s['delta']:.3f} | "
              f"target=${s['target_price']} | stop=${s['stop_price']} | "
              f"risk/ct=${s['risk_per_contract']} | score={s['score']}")
