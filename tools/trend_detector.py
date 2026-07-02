"""
Trend Detector — Decides at 9:28 AM whether to scalp or ride the trend.

Scans gap size, VIX, sector alignment, and pre-market volume to determine
if today is a "trend day" (let runners work) or "chop day" (quick exits).
"""

import yfinance as yf
from typing import Dict
from loguru import logger


def detect_market_trend(symbols: list = None) -> Dict:
    """
    Analyze pre-market conditions to determine trend strength.
    
    Returns:
        {
            "trend_mode": "scalp" | "trend",
            "trend_score": 0-100,
            "gap_pct": {...},
            "vix_level": float,
            "sector_alignment": bool,
            "recommendation": str,
        }
    """
    symbols = symbols or ["SPY", "QQQ", "TSLA"]
    
    # Fetch gap data for all symbols
    gaps = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d", interval="1d")
            if len(hist) < 2:
                continue
            prior_close = float(hist["Close"].iloc[-2])
            
            # Try pre-market
            try:
                fast = ticker.history(period="1d", interval="1m")
                current = float(fast["Close"].iloc[-1]) if len(fast) > 0 else prior_close
            except Exception:
                current = prior_close
            
            gap_pct = ((current - prior_close) / prior_close) * 100 if prior_close else 0.0
            gaps[sym] = {
                "gap_pct": round(gap_pct, 2),
                "prior_close": round(prior_close, 2),
                "current": round(current, 2),
            }
        except Exception as e:
            logger.warning(f"Trend detector: gap fetch failed for {sym}: {e}")
    
    if not gaps:
        return {"trend_mode": "scalp", "trend_score": 0, "recommendation": "No data — default to scalp"}
    
    # Calculate metrics
    avg_gap = sum(abs(g["gap_pct"]) for g in gaps.values()) / len(gaps)
    max_gap = max(abs(g["gap_pct"]) for g in gaps.values())
    
    # Sector alignment: all gaps in same direction?
    directions = [1 if g["gap_pct"] > 0 else -1 if g["gap_pct"] < 0 else 0 for g in gaps.values()]
    aligned = all(d == directions[0] for d in directions) and directions[0] != 0
    
    # VIX level
    vix_level = 0
    try:
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="2d")
        if len(vix_hist) > 0:
            vix_level = float(vix_hist["Close"].iloc[-1])
    except Exception:
        pass
    
    # TREND SCORE CALCULATION
    score = 0
    
    # Gap size contribution (0-40 points)
    if avg_gap >= 2.0:
        score += 40
    elif avg_gap >= 1.5:
        score += 35
    elif avg_gap >= 1.0:
        score += 25
    elif avg_gap >= 0.8:
        score += 15
    elif avg_gap >= 0.5:
        score += 10
    else:
        score += 5
    
    # Sector alignment (0-20 points)
    if aligned:
        score += 20
    else:
        score += 0
    
    # VIX contribution (0-20 points) — higher VIX = bigger moves
    if vix_level >= 30:
        score += 20
    elif vix_level >= 25:
        score += 15
    elif vix_level >= 20:
        score += 10
    elif vix_level >= 15:
        score += 5
    
    # Max gap bonus (0-20 points) — if one symbol is gapping huge
    if max_gap >= 3.0:
        score += 20
    elif max_gap >= 2.0:
        score += 15
    elif max_gap >= 1.5:
        score += 10
    elif max_gap >= 1.0:
        score += 5
    
    score = min(100, score)
    
    # DECISION
    if score >= 60:
        mode = "trend"
        rec = f"TREND DAY: avg_gap={avg_gap:.2f}%, aligned={aligned}, vix={vix_level:.1f}. Let runners work with 30% trail."
    elif score >= 40:
        mode = "trend"
        rec = f"MODERATE TREND: avg_gap={avg_gap:.2f}%, aligned={aligned}. Use 25% trail after partials."
    else:
        mode = "scalp"
        rec = f"SCALP MODE: avg_gap={avg_gap:.2f}%, aligned={aligned}, vix={vix_level:.1f}. Quick exits only."
    
    logger.info(f"Trend detector: {rec}")
    
    return {
        "trend_mode": mode,
        "trend_score": score,
        "gaps": gaps,
        "avg_gap": round(avg_gap, 2),
        "max_gap": round(max_gap, 2),
        "vix_level": round(vix_level, 2),
        "sector_alignment": aligned,
        "recommendation": rec,
    }


def get_exit_params(trend_result: Dict) -> Dict:
    """Get exit parameters based on trend mode."""
    mode = trend_result.get("trend_mode", "scalp")
    
    if mode == "trend":
        return {
            "tier_1_pl": 40,           # Sell 50% at +$0.40
            "tier_2_pl": 80,           # Sell 25% at +$0.80
            "tier_3_pl": 150,          # Sell 15% at +$1.50 (runner)
            "tier_4_pl": 250,          # Trail last 10% at +$2.50
            "max_hold_minutes": 45,    # Give trend 45 min
            "trail_pct": 0.30,         # 30% trail on runner
            "flat_exit_threshold": -15, # Tolerate -$15 on trend days
        }
    else:
        return {
            "tier_1_pl": 40,
            "tier_2_pl": 80,
            "tier_3_pl": 999,          # DISABLED
            "tier_4_pl": 999,          # DISABLED
            "max_hold_minutes": 20,    # 20 min max
            "trail_pct": 0.30,
            "flat_exit_threshold": 0,  # Cut if not green
        }
