"""
Order Flow Engine

Implements:
- CVD (Cumulative Volume Delta) tracking
- Extreme delta detection
- Divergence detection
- Exhaustion detection
- Volume analysis
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum
import numpy as np
from loguru import logger


class CVDState(Enum):
    CONFIRMING = "confirming"
    DIVERGING = "diverging"
    EXHAUSTING = "exhausting"
    NEUTRAL = "neutral"


class VolumeState(Enum):
    NORMAL = "normal"
    EXPANSION = "expansion"
    CLIMAX = "climax"
    CONTRACTION = "contraction"


@dataclass
class CVDData:
    values: np.ndarray
    current: float
    session_high: float
    session_low: float
    is_extreme: bool
    state: CVDState


@dataclass
class OrderFlowSignals:
    cvd: CVDData
    volume_state: VolumeState
    delta_extreme: bool
    divergence_detected: bool
    exhaustion_detected: bool
    footprint_signal: str  # "absorption", "failed_imbalance", "one_sided", "none"
    flow_score: int  # 0-25 for A+ system


def calculate_cvd(
    ticks: List[Dict],
    reset_on_session: bool = True
) -> CVDData:
    """
    Calculate Cumulative Volume Delta from tick data.

    Args:
        ticks: List of {'price': float, 'volume': int, 'side': 'buy'|'sell'}
        reset_on_session: Reset CVD at session start

    Returns:
        CVDData with running CVD values and state
    """
    if not ticks:
        return CVDData(
            values=np.array([0]),
            current=0,
            session_high=0,
            session_low=0,
            is_extreme=False,
            state=CVDState.NEUTRAL
        )

    cvd_values = []
    running_cvd = 0

    for tick in ticks:
        volume = tick['volume']
        side = tick.get('side', 'unknown')

        if side == 'buy':
            running_cvd += volume
        elif side == 'sell':
            running_cvd -= volume
        # If side unknown, use price movement heuristic

        cvd_values.append(running_cvd)

    cvd_array = np.array(cvd_values)
    session_high = np.max(cvd_array)
    session_low = np.min(cvd_array)
    current = cvd_array[-1]

    # Determine if extreme (within 10% of session high/low)
    range_size = session_high - session_low
    if range_size > 0:
        high_threshold = session_high - (range_size * 0.1)
        low_threshold = session_low + (range_size * 0.1)
        is_extreme = current >= high_threshold or current <= low_threshold
    else:
        is_extreme = False

    # Determine state (simplified - would need price data for full analysis)
    state = CVDState.NEUTRAL
    if is_extreme:
        state = CVDState.CONFIRMING  # At extreme, likely confirming trend

    return CVDData(
        values=cvd_array,
        current=current,
        session_high=session_high,
        session_low=session_low,
        is_extreme=is_extreme,
        state=state
    )


def detect_divergence(
    prices: List[float],
    cvd: CVDData,
    lookback: int = 20
) -> bool:
    """
    Detect price/CVD divergence.

    Bearish divergence: Price makes higher high, CVD makes lower high
    Bullish divergence: Price makes lower low, CVD makes higher low
    """
    if len(prices) < lookback or len(cvd.values) < lookback:
        return False

    recent_prices = prices[-lookback:]
    recent_cvd = cvd.values[-lookback:]

    # Find recent highs/lows
    price_high_idx = np.argmax(recent_prices)
    price_low_idx = np.argmin(recent_prices)
    cvd_high_idx = np.argmax(recent_cvd)
    cvd_low_idx = np.argmin(recent_cvd)

    # Check for bearish divergence (price high after CVD high)
    if price_high_idx > cvd_high_idx:
        if recent_prices[price_high_idx] > recent_prices[cvd_high_idx]:
            if recent_cvd[price_high_idx] < recent_cvd[cvd_high_idx]:
                return True  # Bearish divergence

    # Check for bullish divergence (price low after CVD low)
    if price_low_idx > cvd_low_idx:
        if recent_prices[price_low_idx] < recent_prices[cvd_low_idx]:
            if recent_cvd[price_low_idx] > recent_cvd[cvd_low_idx]:
                return True  # Bullish divergence

    return False


def detect_exhaustion(
    cvd: CVDData,
    prices: List[float],
    volume: List[float],
    lookback: int = 10
) -> bool:
    """
    Detect exhaustion: CVD flattens while price continues trending.
    """
    if len(prices) < lookback or len(cvd.values) < lookback:
        return False

    recent_cvd = cvd.values[-lookback:]
    recent_prices = prices[-lookback:]

    # Calculate CVD slope (should be flattening)
    cvd_slope = (recent_cvd[-1] - recent_cvd[0]) / lookback

    # Calculate price slope (should be continuing)
    price_slope = (recent_prices[-1] - recent_prices[0]) / lookback

    # Exhaustion: price moving but CVD flattening
    cvd_range = np.max(recent_cvd) - np.min(recent_cvd)
    price_range = np.max(recent_prices) - np.min(recent_prices)

    if price_range > 0:
        # CVD should be relatively flat compared to price movement
        cvd_normalized = abs(cvd_slope) / (cvd_range + 1)
        price_normalized = abs(price_slope) / price_range

        if price_normalized > 0.5 and cvd_normalized < 0.2:
            return True

    return False


def analyze_volume(
    volumes: List[float],
    lookback: int = 20,
    expansion_threshold: float = 1.5,
    climax_threshold: float = 3.0
) -> VolumeState:
    """
    Analyze volume relative to session average.
    """
    if not volumes or len(volumes) < lookback:
        return VolumeState.NORMAL

    recent = volumes[-lookback:]
    avg_volume = np.mean(recent[:-1])  # Average excluding current
    current_volume = recent[-1]

    if avg_volume == 0:
        return VolumeState.NORMAL

    ratio = current_volume / avg_volume

    if ratio >= climax_threshold:
        return VolumeState.CLIMAX
    elif ratio >= expansion_threshold:
        return VolumeState.EXPANSION
    elif ratio <= 0.5:
        return VolumeState.CONTRACTION
    else:
        return VolumeState.NORMAL


def detect_absorption(
    bid_volume: float,
    ask_volume: float,
    price_change: float,
    threshold: float = 2.0
) -> bool:
    """
    Detect absorption: Large volume on one side but price doesn't move.
    """
    total_volume = bid_volume + ask_volume
    if total_volume == 0:
        return False

    imbalance = abs(bid_volume - ask_volume) / total_volume

    # High imbalance but small price change = absorption
    if imbalance > 0.6 and abs(price_change) < 0.1:  # Adjust thresholds as needed
        return True

    return False


def get_order_flow_signals(
    ticks: List[Dict] = None,
    prices: List[float] = None,
    volumes: List[float] = None,
    ohlcv_data: List[Dict] = None,
    **kwargs
) -> OrderFlowSignals:
    """
    Get comprehensive order flow analysis.

    Returns:
        OrderFlowSignals with all signals and A+ flow score (0-25)
    """
    # Extract from OHLCV if provided
    if ohlcv_data and not prices:
        prices = [b['close'] for b in ohlcv_data]
    if ohlcv_data and not volumes:
        volumes = [b['volume'] for b in ohlcv_data]

    # Calculate CVD
    cvd = calculate_cvd(ticks or [])

    # Analyze volume
    volume_state = analyze_volume(volumes or [])

    # Detect signals
    divergence = detect_divergence(prices or [], cvd) if prices else False
    exhaustion = detect_exhaustion(cvd, prices or [], volumes or []) if prices else False

    # Determine CVD state
    if divergence:
        cvd.state = CVDState.DIVERGING
    elif exhaustion:
        cvd.state = CVDState.EXHAUSTING
    elif cvd.is_extreme:
        cvd.state = CVDState.CONFIRMING

    # Calculate flow score (0-25)
    score = 0

    # CVD confirmation (0-15 points)
    if cvd.state == CVDState.CONFIRMING:
        score += 15
    elif cvd.state == CVDState.DIVERGING:
        score += 10  # Divergence is good for reversal trades
    elif cvd.state == CVDState.EXHAUSTING:
        score += 8

    # Volume expansion (0-5 points)
    if volume_state == VolumeState.EXPANSION:
        score += 5
    elif volume_state == VolumeState.CLIMAX:
        score += 3  # Climax can signal reversal

    # Footprint signals (0-5 points)
    footprint_signal = "none"
    # Would need real footprint data for this

    return {
        'cvd': {
            'values': cvd.values.tolist(),
            'current': cvd.current,
            'session_high': cvd.session_high,
            'session_low': cvd.session_low,
            'is_extreme': cvd.is_extreme,
            'state': cvd.state.value
        },
        'volume_state': volume_state.value,
        'delta_extreme': cvd.is_extreme,
        'divergence_detected': divergence,
        'exhaustion_detected': exhaustion,
        'footprint_signal': footprint_signal,
        'flow_score': min(score, 25)
    }

    