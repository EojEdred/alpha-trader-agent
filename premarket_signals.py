import asyncio
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

import os

from tools.options_multi_scalper import (
    _GAP_SYMBOLS,
    _fetch_gap_data,
    _fetch_premarket_intraday,
    _gap_to_direction,
    _gap_to_score,
    _gap_to_contracts,
    _MIN_GAP_PCT,
    _MAX_GAP_PCT,
)
from tools.schwab import schwab_get_option_chain_parsed, schwab_check_compliance

_PREMARKET_REVERSAL_ENABLED = (
    os.getenv("PREMARKET_REVERSAL_ENABLED", "false").lower() == "true"
)
_PREMARKET_REVERSAL_MODE = os.getenv("PREMARKET_REVERSAL_MODE", "confirm").lower()
_PREMARKET_REVERSAL_MIN_VOLUME_RATIO = float(
    os.getenv("PREMARKET_REVERSAL_MIN_VOLUME_RATIO", "1.0")
)
_REVERSAL_STRATEGY = os.getenv("REVERSAL_STRATEGY", "mean_reversion").lower()

async def generate_signals():
    print("=" * 70)
    print(f"PRE-MARKET GAP SIGNALS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    compliance = await schwab_check_compliance()
    print(f"Buying Power: ${compliance.get('buying_power', 0):,.2f}")
    print(f"Can Trade: {compliance.get('can_trade', False)}")
    if not compliance.get("can_trade", True):
        print(f"Reason: {compliance.get('reason')}")
        return []
    print("-" * 70)
    
    signals = []
    for symbol in _GAP_SYMBOLS:
        gap_data = _fetch_gap_data(symbol)
        gap_pct = gap_data["gap_pct"]
        prior_close = gap_data["prior_close"]
        current = gap_data["current"]
        direction = _gap_to_direction(gap_pct)
        score = _gap_to_score(gap_pct)
        
        print(f"\n{symbol}: prior_close=${prior_close:.2f} current=${current:.2f} gap={gap_pct:+.2f}%")
        
        if direction == "none" or score < 40:
            print(f"  → NO ENTRY (gap below {_MIN_GAP_PCT}% threshold or score {score})")
            continue
        
        if abs(gap_pct) > _MAX_GAP_PCT:
            print(f"  → NO ENTRY (gap exceeds {_MAX_GAP_PCT}% max safety threshold)")
            continue
        
        # BB/VWAP/VOLUME REVERSAL CRITERION
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
            
            if direction == "long":
                gap_aligned_modifier = rev_modifier
            elif direction == "short":
                gap_aligned_modifier = -rev_modifier
            else:
                gap_aligned_modifier = 0
            
            print(
                f"  reversal={rev_signal} direction={rev_direction} "
                f"strength={rev_strength} modifier={gap_aligned_modifier}"
            )
            
            if _PREMARKET_REVERSAL_MODE == "filter":
                if (
                    rev_direction != "none"
                    and rev_direction != direction
                    and rev_strength >= 0.5
                ):
                    print(f"  → NO ENTRY (reversal conflicts with gap direction)")
                    continue
            elif _PREMARKET_REVERSAL_MODE == "fade":
                if (
                    rev_direction != "none"
                    and rev_direction != direction
                    and rev_strength >= 0.7
                ):
                    old_direction = direction
                    direction = rev_direction
                    gap_pct = -gap_pct
                    print(f"  → FADING gap: {old_direction} -> {direction}")
            
            score = max(0, min(100, score + gap_aligned_modifier))
        
        if direction == "none" or score < 40:
            print(f"  → NO ENTRY (post-reversal score {score})")
            continue
        
        # Fetch option chain with correct direction
        option_chain = await schwab_get_option_chain_parsed(symbol, direction=direction)
        if "error" in option_chain:
            print(f"  → OPTION CHAIN ERROR: {option_chain['error']}")
            continue
        
        strikes = option_chain.get("strikes", [])
        underlying_price = option_chain.get("underlying_price", gap_data["current"])
        
        if underlying_price <= 0 or not strikes:
            print(f"  → NO ENTRY: invalid underlying price or no strikes")
            continue
        
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
            print(f"  → NO ENTRY: no ATM strike found")
            continue
        
        option_type = "CALL" if direction == "long" else "PUT"
        
        # Build option symbol
        today = datetime.now().strftime("%Y-%m-%d")
        exp_dt = datetime.strptime(today, "%Y-%m-%d")
        exp_str = exp_dt.strftime("%y%m%d")
        strike_str = f"{int(atm_strike * 1000):08d}"
        option_symbol = f"{symbol}   {exp_str}{option_type[0]}{strike_str}"
        
        # Limit price at mid, never above ask
        bid = atm_data.get("bid", 0)
        ask = atm_data.get("ask", 0)
        if bid and ask:
            spread = ask - bid
            mid = round(bid + spread * 0.5, 2)
            limit_price = min(mid, ask)
        else:
            limit_price = round(atm_data.get("last", atm_strike * 0.01), 2)
        
        if limit_price <= 0:
            print(f"  → NO ENTRY: invalid limit price {limit_price}")
            continue
        
        quantity = _gap_to_contracts(gap_pct)
        max_cost = compliance.get("buying_power", 4000)
        estimated_cost = limit_price * 100 * quantity
        if estimated_cost > max_cost * 0.25:
            quantity = max(1, int((max_cost * 0.25) / (limit_price * 100)))
        
        signal = {
            "symbol": symbol,
            "direction": direction,
            "option_type": option_type,
            "option_symbol": option_symbol,
            "strike": atm_strike,
            "expiration": today,
            "quantity": quantity,
            "limit_price": limit_price,
            "gap_pct": gap_pct,
            "score": score,
            "underlying_price": underlying_price,
            "bid": bid,
            "ask": ask,
            "estimated_cost": limit_price * 100 * quantity,
        }
        if _PREMARKET_REVERSAL_ENABLED and reversal_info:
            signal["reversal"] = {
                "signal": reversal_info.get("signal"),
                "direction": reversal_info.get("direction"),
                "strength": reversal_info.get("strength"),
                "volume_ratio": reversal_info.get("volume_ratio"),
                "vwap": reversal_info.get("vwap"),
                "bb_bands": reversal_info.get("bb_bands"),
                "reasons": reversal_info.get("reasons"),
            }
        signals.append(signal)
        
        print(f"  → ENTRY SIGNAL:")
        print(f"     Direction:    {direction.upper()}")
        print(f"     Option:       {option_symbol}")
        print(f"     Type:         {option_type}")
        print(f"     Strike:       ${atm_strike:.2f}")
        print(f"     Qty:          {quantity}")
        print(f"     Limit Price:  ${limit_price:.2f}")
        print(f"     Bid/Ask:      ${bid:.2f} / ${ask:.2f}")
        print(f"     Est. Cost:    ${signal['estimated_cost']:.2f}")
        print(f"     Score:        {score}/100")
        if _PREMARKET_REVERSAL_ENABLED and reversal_info:
            print(
                f"     Reversal:     {reversal_info.get('signal')} "
                f"strength={reversal_info.get('strength')} "
                f"vol_ratio={reversal_info.get('volume_ratio')}"
            )
    
    print("\n" + "=" * 70)
    print(f"TOTAL SIGNALS: {len(signals)}")
    print("=" * 70)
    return signals

async def main():
    signals = await generate_signals()
    # Save signals to file for reference
    with open("premarket_signals.json", "w") as f:
        json.dump(signals, f, indent=2)
    print("\nSignals saved to premarket_signals.json")

if __name__ == "__main__":
    asyncio.run(main())
