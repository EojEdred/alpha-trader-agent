"""
A+ Scoring Engine

Deterministic scoring system for trade setups:
- Location Score (0-25)
- Order Flow Score (0-25)
- Setup Quality Score (0-25)
- Regime Alignment Score (0-25)

Total: 0-100
Grades: A+ (85+), A (75-84), B (60-74), C (<60 = NO TRADE)
"""

from dataclasses import dataclass
from typing import Dict, Optional, List
from enum import Enum
from datetime import datetime
from loguru import logger


class TradeGrade(Enum):
    A_PLUS = "A_PLUS"
    A = "A"
    B = "B"
    NO_TRADE = "NO_TRADE"


class SetupType(Enum):
    POC_BOUNCE = "poc_bounce"
    FVA_EDGE_FADE = "fva_edge_fade"
    LVN_BREAKOUT = "lvn_breakout"
    NONE = "none"


@dataclass
class ScoreBreakdown:
    location_pts: int
    flow_pts: int
    setup_pts: int
    regime_pts: int
    total: int
    grade: TradeGrade
    setup_type: SetupType
    size_modifier: float  # 1.0 for A+/A, 0.5 for B, 0 for C
    trade_allowed: bool
    notes: List[str]


async def score_setup(
    symbol: str,
    current_price: float = None,
    config=None,
    **kwargs
) -> ScoreBreakdown:
    """
    Score a trading setup using the A+ system.

    Fetches all required data and returns comprehensive score.
    """
    from tools.volume_profile import calculate_profile_for_symbol, get_trade_location
    from tools.order_flow import get_order_flow_signals
    from tools.analysis import calculate_technicals
    from tools.market_data import fetch_current_price, fetch_ohlcv

    logger.info(f"Scoring setup for {symbol}")
    notes = []

    # Get current price if not provided
    if current_price is None:
        price_data = await fetch_current_price(symbol)
        current_price = price_data.get('price', 0)

    # 1. LOCATION SCORE (0-25)
    profile_data = await calculate_profile_for_symbol(symbol)
    if 'error' in profile_data:
        location_pts = 0
        notes.append("Could not calculate volume profile")
    else:
        from tools.volume_profile import VolumeProfile, VolumeNode, get_trade_location

        # Reconstruct profile object for location check
        # Create dummy price_levels array for the get_trade_location function
        import numpy as np
        dummy_price_levels = np.array([current_price - 10, current_price, current_price + 10])  # Simple array
        dummy_volumes = np.array([100, 200, 100])  # Dummy volumes

        profile = VolumeProfile(
            price_levels=dummy_price_levels,
            volumes=dummy_volumes,
            poc=profile_data['poc'],
            poc_volume=0,
            value_area_high=profile_data['value_area_high'],
            value_area_low=profile_data['value_area_low'],
            fva_high=profile_data['fva_high'],
            fva_low=profile_data['fva_low'],
            hvn_levels=[VolumeNode(h['price'], h['volume'], 'hvn') for h in profile_data['hvn_levels']],
            lvn_levels=[VolumeNode(l['price'], l['volume'], 'lvn') for l in profile_data['lvn_levels']],
            total_volume=profile_data['total_volume']
        )

        location = get_trade_location(current_price, profile)
        location_pts = location.score
        notes.append(f"Location: {location.location_type.value} ({location_pts}pts)")

    # 2. ORDER FLOW SCORE (0-25)
    flow_signals = get_order_flow_signals()  # Would need real tick data
    flow_pts = flow_signals.get('flow_score', 0)
    notes.append(f"Order flow: {flow_signals.get('cvd', {}).get('state', 'neutral')} ({flow_pts}pts)")

    # 3. SETUP QUALITY SCORE (0-25)
    setup_type, setup_pts = _classify_setup(
        location_pts, flow_signals, profile_data if 'error' not in profile_data else None
    )
    notes.append(f"Setup: {setup_type.value} ({setup_pts}pts)")

    # 4. REGIME ALIGNMENT SCORE (0-25)
    ohlcv = await fetch_ohlcv(symbol, "1h", 50)
    if ohlcv:
        technicals = calculate_technicals(ohlcv)
        regime_pts = _score_regime(technicals)
        notes.append(f"Regime: {technicals.get('trend', 'neutral')} ({regime_pts}pts)")
    else:
        regime_pts = 10  # Neutral default
        notes.append("Could not determine regime")

    # Calculate total and grade
    total = location_pts + flow_pts + setup_pts + regime_pts
    grade = _calculate_grade(total)

    # Size modifier
    size_modifiers = {
        TradeGrade.A_PLUS: 1.0,
        TradeGrade.A: 1.0,
        TradeGrade.B: 0.5,
        TradeGrade.NO_TRADE: 0.0
    }

    return ScoreBreakdown(
        location_pts=location_pts,
        flow_pts=flow_pts,
        setup_pts=setup_pts,
        regime_pts=regime_pts,
        total=total,
        grade=grade,
        setup_type=setup_type,
        size_modifier=size_modifiers[grade],
        trade_allowed=grade != TradeGrade.NO_TRADE,
        notes=notes
    )


def _classify_setup(
    location_pts: int,
    flow_signals: Dict,
    profile_data: Optional[Dict]
) -> tuple:
    """Classify the setup type and score quality."""

    # Determine setup type based on location
    if location_pts >= 23:  # At POC
        setup_type = SetupType.POC_BOUNCE
        base_score = 20
    elif location_pts >= 18:  # At FVA edge
        setup_type = SetupType.FVA_EDGE_FADE
        base_score = 18
    elif location_pts >= 15:  # At LVN
        setup_type = SetupType.LVN_BREAKOUT
        base_score = 15
    else:
        setup_type = SetupType.NONE
        base_score = 0

    # Adjust for flow confirmation
    cvd_state = flow_signals.get('cvd', {}).get('state')
    if cvd_state == "confirming":
        base_score += 5
    elif flow_signals.get('divergence_detected'):
        base_score += 3

    return setup_type, min(base_score, 25)


def _score_regime(technicals: Dict) -> int:
    """Score regime alignment (0-25)."""
    score = 10  # Start neutral

    trend = technicals.get('trend', 'neutral')
    if trend == 'bullish':
        score += 8
    elif trend == 'bearish':
        score += 8
    # Neutral trend is okay but not ideal

    # RSI not extreme
    rsi = technicals.get('indicators', {}).get('rsi_14', 50)
    if 30 <= rsi <= 70:
        score += 5
    elif rsi < 30 or rsi > 70:
        score += 2  # Extreme can work for reversals

    return min(score, 25)


def _calculate_grade(total: int) -> TradeGrade:
    """Convert total score to grade."""
    if total >= 85:
        return TradeGrade.A_PLUS
    elif total >= 75:
        return TradeGrade.A
    elif total >= 60:
        return TradeGrade.B
    else:
        return TradeGrade.NO_TRADE


def create_trade_object(
    symbol: str,
    direction: str,
    score: ScoreBreakdown,
    profile_data: Dict,
    entry_price: float,
    config=None
) -> Dict:
    """
    Create standardized trade object from scored setup.
    """
    # Calculate stops and targets based on profile
    poc = profile_data.get('poc', entry_price)
    fva_high = profile_data.get('fva_high', entry_price * 1.01)
    fva_low = profile_data.get('fva_low', entry_price * 0.99)

    if direction == 'long':
        stop = fva_low - (fva_high - fva_low) * 0.1  # Below FVA
        target1 = poc
        target2 = fva_high
    else:
        stop = fva_high + (fva_high - fva_low) * 0.1  # Above FVA
        target1 = poc
        target2 = fva_low

    risk_per_share = abs(entry_price - stop)

    return {
        'id': f"trade_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        'symbol': symbol,
        'direction': direction,
        'strategy_template_id': score.setup_type.value,

        'location': {
            'type': score.setup_type.value,
            'price_level': entry_price,
            'distance_from_poc': abs(entry_price - poc)
        },

        'score': {
            'location_pts': score.location_pts,
            'flow_pts': score.flow_pts,
            'setup_pts': score.setup_pts,
            'regime_pts': score.regime_pts,
            'total': score.total,
            'grade': score.grade.value
        },

        'entry': {
            'trigger': f"Limit at {entry_price}",
            'price': entry_price,
            'order_type': 'limit'
        },

        'stop': {
            'price': stop,
            'type': 'structural',
            'reason': 'Below FVA' if direction == 'long' else 'Above FVA'
        },

        'targets': {
            't1': {'price': target1, 'size_pct': 50, 'reason': 'POC'},
            't2': {'price': target2, 'size_pct': 50, 'reason': 'FVA edge'}
        },

        'risk': {
            'risk_per_share': risk_per_share,
            'size_modifier': score.size_modifier
        },

        'execution': {
            'mode': 'SIGNAL_ONLY',  # Default, router will determine
            'venue': 'auto',
            'state': 'SCORED'
        },

        'created_at': datetime.utcnow().isoformat()
    }