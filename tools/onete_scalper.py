"""
1DTE Options Scalper

Trades SPY/QQQ/TSLA 1-day-to-expiration options.
- Enters on gap/momentum
- Tight stop and target
- Same-day exit
- Max 1-2 contracts, max $100 risk per trade
"""

import asyncio
from datetime import date, timedelta, datetime
from typing import Dict, List, Optional
from loguru import logger

SYMBOLS = ["SPY", "QQQ", "TSLA"]
MIN_GAP_PCT = 0.30
MAX_GAP_PCT = 5.0
MIN_SCORE = 40
MAX_RISK_DOLLARS = 100
MAX_POSITIONS = 1


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
    bonus = min(int((abs_gap - MIN_GAP_PCT) * 15), 40)
    return base + bonus


def _fetch_gap_data(symbol: str) -> Dict:
    """Fetch prior day close and current pre-market/regular price for gap calc."""
    import yfinance as yf
    try:
        ticker = yf.Ticker(symbol)
        # Daily history for prior close
        daily = ticker.history(period="5d", interval="1d")
        if daily.empty or len(daily) < 2:
            return {"gap_pct": 0.0, "prior_close": 0.0, "current": 0.0}
        prior_close = float(daily["Close"].iloc[-2])
        # Intraday for current price
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


async def find_onete_setups() -> List[Dict]:
    """Find all 1DTE directional setups."""
    from tools.schwab import SchwabClient
    
    client = SchwabClient()
    expiration = date.today() + timedelta(days=1)
    setups = []
    
    for symbol in SYMBOLS:
        gap_data = _fetch_gap_data(symbol)
        gap_pct = gap_data["gap_pct"]
        direction = _gap_to_direction(gap_pct)
        score = _gap_to_score(gap_pct)
        
        if direction == "none" or score < MIN_SCORE:
            continue
        
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
                continue
            exp_key = sorted(exp_map.keys())[0]
            actual_exp = datetime.strptime(exp_key.split(':')[0], "%Y-%m-%d").date()
            underlying = float(data.get('underlyingPrice', gap_data['current']))
            strikes_data = exp_map[exp_key]
            
            # Find ATM
            atm_key = None
            atm_strike = None
            min_dist = float('inf')
            for k in strikes_data.keys():
                s = float(k)
                dist = abs(s - underlying)
                if dist < min_dist:
                    min_dist = dist
                    atm_strike = s
                    atm_key = k
            
            if not atm_key:
                continue
            
            opt = strikes_data[atm_key][0]
            bid = float(opt.get('bid', 0))
            ask = float(opt.get('ask', 0))
            mid = round((bid + ask) / 2, 2)
            delta = float(opt.get('delta', 0))
            option_type = "CALL" if direction == "long" else "PUT"
            option_symbol = _build_option_symbol(symbol, actual_exp, atm_strike, option_type)
            
            # Risk: 20% stop on option premium
            stop_price = round(mid * 0.80, 2)
            risk_per_contract = round((mid - stop_price) * 100, 2)
            target_price = round(mid * 1.30, 2)  # 30% target
            
            setups.append({
                "symbol": symbol,
                "direction": direction,
                "option_type": option_type,
                "option_symbol": option_symbol,
                "strike": atm_strike,
                "expiration": actual_exp.isoformat(),
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
                "max_contracts": max(1, int(MAX_RISK_DOLLARS / risk_per_contract)) if risk_per_contract > 0 else 1,
            })
        except Exception as e:
            logger.error(f"1DTE scan error for {symbol}: {e}")
    
    setups.sort(key=lambda x: x['score'], reverse=True)
    return setups


async def enter_best_onete(max_risk: float = MAX_RISK_DOLLARS) -> Dict:
    """Enter the best 1DTE setup if available."""
    from tools.schwab import schwab_get_positions, schwab_place_option_order, schwab_check_compliance
    
    compliance = await schwab_check_compliance()
    if not compliance.get("can_trade", True):
        return {"action": "none", "reason": compliance.get("reason")}
    
    positions = await schwab_get_positions()
    option_positions = [p for p in positions if p.get("asset_type") == "OPTION"]
    if len(option_positions) >= MAX_POSITIONS:
        return {"action": "none", "reason": f"Max {MAX_POSITIONS} option position(s) open"}
    
    setups = await find_onete_setups()
    if not setups:
        return {"action": "none", "reason": "No 1DTE setups found"}
    
    best = setups[0]
    
    # Limit quantity by risk and buying power
    buying_power = compliance.get("buying_power", 0)
    max_by_risk = max(1, int(max_risk / best['risk_per_contract'])) if best['risk_per_contract'] > 0 else 1
    max_by_bp = max(1, int(buying_power * 0.25 / (best['mid'] * 100)))
    quantity = min(max_by_risk, max_by_bp, 2)  # never more than 2 contracts
    
    # Place limit order at mid
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
    setups = asyncio.run(find_onete_setups())
    for s in setups:
        print(f"{s['symbol']} {s['option_type']} | {s['option_symbol']} | "
              f"strike=${s['strike']} | mid=${s['mid']} | "
              f"target=${s['target_price']} | stop=${s['stop_price']} | "
              f"risk/ct=${s['risk_per_contract']} | score={s['score']}")
