"""
Credit Spread Strategy — reliable income with defined risk.

Focus: SPY/QQQ put credit spreads, 7-60 DTE, ~30 delta short strike.
Goal: Steady account growth, avoid 0DTE gamma risk.
"""

import asyncio
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

WATCHLIST = ["SPY", "QQQ"]
DEFAULT_DTE = 7
MIN_CREDIT = 0.50
MAX_DELTA = 0.35
MIN_POP = 0.65
MAX_RISK_PER_TRADE = 500  # dollars
MAX_POSITIONS = 2


def _build_option_symbol(underlying: str, expiration: date, strike: float, option_type: str) -> str:
    exp_str = expiration.strftime("%y%m%d")
    letter = option_type[0].upper()
    strike_str = f"{int(strike * 1000):08d}"
    return f"{underlying:<6}{exp_str}{letter}{strike_str}"


async def find_put_credit_spreads(
    symbol: str,
    dte: int = DEFAULT_DTE,
    spread_width: float = 5.0,
    max_delta: float = MAX_DELTA,
    min_credit: float = MIN_CREDIT,
) -> List[Dict]:
    """Find put credit spread opportunities for a symbol."""
    from tools.schwab import SchwabClient
    
    client = SchwabClient()
    expiration = date.today() + timedelta(days=dte)
    
    try:
        resp = client.client.get_option_chain(
            symbol,
            contract_type=client.client.Options.ContractType.PUT,
            from_date=expiration,
            to_date=expiration
        )
        data = resp.json()
    except Exception as e:
        logger.error(f"Credit spread: failed to fetch chain for {symbol}: {e}")
        return []
    
    if 'putExpDateMap' not in data or not data['putExpDateMap']:
        logger.warning(f"Credit spread: no put chain for {symbol} {expiration}")
        return []
    
    exp_map = data['putExpDateMap']
    exp_key = sorted(exp_map.keys())[0]
    actual_exp = datetime.strptime(exp_key.split(':')[0], "%Y-%m-%d").date()
    strikes_data = exp_map[exp_key]
    underlying = float(data.get('underlyingPrice', 0))
    
    candidates = []
    # Preserve original string keys
    strike_keys = sorted(strikes_data.keys(), key=lambda k: float(k))
    strikes = [float(k) for k in strike_keys]
    
    for short_key, short_strike in zip(strike_keys, strikes):
        if short_strike >= underlying:
            continue  # skip ITM
        short_opt = strikes_data[short_key]
        if not short_opt:
            continue
        short_opt = short_opt[0]
        short_delta = abs(float(short_opt.get('delta', 0)))
        
        if short_delta > max_delta:
            continue
        
        long_strike = short_strike - spread_width
        # Find closest key to long_strike
        long_key = None
        long_dist = float('inf')
        for k in strike_keys:
            dist = abs(float(k) - long_strike)
            if dist < long_dist:
                long_dist = dist
                long_key = k
        if long_key is None or long_dist > 0.01:
            continue
        long_opt = strikes_data[long_key][0]
        
        short_bid = float(short_opt.get('bid', 0))
        short_ask = float(short_opt.get('ask', 0))
        long_bid = float(long_opt.get('bid', 0))
        long_ask = float(long_opt.get('ask', 0))
        
        # Net credit at mid prices
        short_mid = round((short_bid + short_ask) / 2, 2)
        long_mid = round((long_bid + long_ask) / 2, 2)
        net_credit = round(short_mid - long_mid, 2)
        
        if net_credit < min_credit:
            continue
        
        max_risk = spread_width - net_credit
        pop = 1 - short_delta  # rough estimate
        
        candidates.append({
            "symbol": symbol,
            "underlying_price": underlying,
            "expiration": actual_exp.isoformat(),
            "dte": short_opt.get('daysToExpiration', dte),
            "short_strike": short_strike,
            "long_strike": long_strike,
            "spread_width": spread_width,
            "net_credit": net_credit,
            "max_risk": max_risk,
            "short_delta": short_delta,
            "pop": round(pop, 2),
            "roc": round(net_credit / max_risk, 3),
            "short_symbol": _build_option_symbol(symbol, actual_exp, short_strike, "PUT"),
            "long_symbol": _build_option_symbol(symbol, actual_exp, long_strike, "PUT"),
        })
    
    # Sort by best ROC, then by highest POP
    candidates.sort(key=lambda x: (x['roc'], x['pop']), reverse=True)
    return candidates


async def scan_credit_spreads() -> List[Dict]:
    """Scan watchlist for best put credit spreads."""
    all_spreads = []
    for symbol in WATCHLIST:
        for dte in [7, 14, 30, 60]:
            spreads = await find_put_credit_spreads(symbol, dte=dte)
            all_spreads.extend(spreads)
    
    # Sort by ROC
    all_spreads.sort(key=lambda x: x['roc'], reverse=True)
    return all_spreads


async def enter_best_credit_spread(max_positions: int = MAX_POSITIONS) -> Dict:
    """Enter the best available put credit spread if criteria met."""
    from tools.schwab import schwab_get_positions, schwab_place_credit_spread, schwab_check_compliance
    
    compliance = await schwab_check_compliance()
    if not compliance.get("can_trade", True):
        return {"action": "none", "reason": compliance.get("reason")}
    
    positions = await schwab_get_positions()
    option_positions = [p for p in positions if p.get("asset_type") == "OPTION"]
    if len(option_positions) >= max_positions:
        return {"action": "none", "reason": f"Max {max_positions} option positions reached"}
    
    spreads = await scan_credit_spreads()
    if not spreads:
        return {"action": "none", "reason": "No credit spread setups found"}
    
    # Pick the best spread that fits buying power
    buying_power = compliance.get("buying_power", 0)
    best = None
    for s in spreads:
        risk = s['max_risk'] * 100  # per contract
        if risk <= min(buying_power * 0.35, MAX_RISK_PER_TRADE) and s['pop'] >= MIN_POP:
            best = s
            break
    
    if not best:
        return {"action": "none", "reason": "No spread fits risk/buying power criteria", "candidates": spreads[:3]}
    
    # Determine quantity — 1 contract for now, keep risk small
    quantity = 1
    
    result = await schwab_place_credit_spread(
        underlying=best['symbol'],
        short_strike=best['short_strike'],
        long_strike=best['long_strike'],
        expiration_date=datetime.fromisoformat(best['expiration']).date(),
        quantity=quantity,
        net_credit=best['net_credit'],
        spread_type="PUT"
    )
    
    if result.get('status') == 'submitted':
        return {"action": "entered", "spread": best, "order": result}
    else:
        return {"action": "failed", "spread": best, "error": result.get('error')}


if __name__ == "__main__":
    spreads = asyncio.run(scan_credit_spreads())
    for s in spreads[:5]:
        print(f"{s['symbol']} {s['dte']}DTE ${s['long_strike']}/${s['short_strike']} PUT | "
              f"credit=${s['net_credit']} risk=${s['max_risk']} delta={s['short_delta']:.3f} "
              f"POP={s['pop']} ROC={s['roc']:.1%}")
