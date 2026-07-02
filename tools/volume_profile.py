"""
Volume Profile Engine

Implements:
- Session profile calculation
- 40% Fair Value Area (FVA)
- Point of Control (POC)
- High/Low Volume Nodes (HVN/LVN)
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum
import numpy as np
from loguru import logger


class LocationType(Enum):
    POC = "poc"
    FVA_EDGE = "fva_edge"
    HVN = "hvn"
    LVN = "lvn"
    VALUE_AREA = "value_area"
    OUTSIDE = "outside"


@dataclass
class VolumeNode:
    price: float
    volume: float
    node_type: str  # "hvn" or "lvn"


@dataclass
class VolumeProfile:
    price_levels: np.ndarray
    volumes: np.ndarray
    poc: float
    poc_volume: float
    value_area_high: float
    value_area_low: float
    fva_high: float  # 40% FVA
    fva_low: float
    hvn_levels: List[VolumeNode]
    lvn_levels: List[VolumeNode]
    total_volume: float


@dataclass
class TradeLocation:
    location_type: LocationType
    price: float
    distance_from_poc: float
    distance_from_fva: float
    nearest_hvn: Optional[float]
    nearest_lvn: Optional[float]
    score: int  # 0-25 for A+ system


def calculate_session_profile(
    bars: List[Dict],
    tick_size: float = 0.25,
    value_area_pct: float = 0.70,
    fva_pct: float = 0.40
) -> VolumeProfile:
    """
    Calculate volume profile from OHLCV bars.

    Args:
        bars: List of dicts with 'high', 'low', 'close', 'volume'
        tick_size: Price increment for bucketing
        value_area_pct: Percentage for value area (default 70%)
        fva_pct: Percentage for fair value area (default 40%)

    Returns:
        VolumeProfile with all computed values
    """
    if not bars:
        raise ValueError("No bars provided")

    # Get price range
    all_highs = [b['high'] for b in bars]
    all_lows = [b['low'] for b in bars]
    price_high = max(all_highs)
    price_low = min(all_lows)

    # Create price buckets
    num_levels = int((price_high - price_low) / tick_size) + 1
    price_levels = np.linspace(price_low, price_high, num_levels)
    volumes = np.zeros(num_levels)

    # Distribute volume across price levels
    for bar in bars:
        bar_high = bar['high']
        bar_low = bar['low']
        bar_volume = bar['volume']

        # Find touched levels
        low_idx = int((bar_low - price_low) / tick_size)
        high_idx = int((bar_high - price_low) / tick_size)

        # Distribute volume equally across touched levels
        touched_levels = high_idx - low_idx + 1
        vol_per_level = bar_volume / touched_levels

        for i in range(low_idx, min(high_idx + 1, num_levels)):
            volumes[i] += vol_per_level

    # Find POC (Point of Control)
    poc_idx = np.argmax(volumes)
    poc = price_levels[poc_idx]
    poc_volume = volumes[poc_idx]

    # Calculate Value Area (70% of volume centered on POC)
    total_volume = np.sum(volumes)
    va_high, va_low = _calculate_value_area(
        price_levels, volumes, poc_idx, total_volume, value_area_pct
    )

    # Calculate FVA (40% - tighter zone)
    fva_high, fva_low = _calculate_value_area(
        price_levels, volumes, poc_idx, total_volume, fva_pct
    )

    # Detect HVN/LVN
    hvn_levels, lvn_levels = _detect_hvn_lvn(price_levels, volumes)

    return VolumeProfile(
        price_levels=price_levels,
        volumes=volumes,
        poc=poc,
        poc_volume=poc_volume,
        value_area_high=va_high,
        value_area_low=va_low,
        fva_high=fva_high,
        fva_low=fva_low,
        hvn_levels=hvn_levels,
        lvn_levels=lvn_levels,
        total_volume=total_volume
    )


def _calculate_value_area(
    price_levels: np.ndarray,
    volumes: np.ndarray,
    poc_idx: int,
    total_volume: float,
    target_pct: float
) -> Tuple[float, float]:
    """Calculate value area bounds containing target_pct of volume."""
    target_volume = total_volume * target_pct
    accumulated = volumes[poc_idx]

    high_idx = poc_idx
    low_idx = poc_idx

    while accumulated < target_volume:
        # Look one level above and below
        can_go_high = high_idx < len(volumes) - 1
        can_go_low = low_idx > 0

        if not can_go_high and not can_go_low:
            break

        vol_above = volumes[high_idx + 1] if can_go_high else 0
        vol_below = volumes[low_idx - 1] if can_go_low else 0

        # Add the side with more volume
        if vol_above >= vol_below and can_go_high:
            high_idx += 1
            accumulated += vol_above
        elif can_go_low:
            low_idx -= 1
            accumulated += vol_below
        elif can_go_high:
            high_idx += 1
            accumulated += vol_above

    return price_levels[high_idx], price_levels[low_idx]


def _detect_hvn_lvn(
    price_levels: np.ndarray,
    volumes: np.ndarray,
    hvn_threshold: float = 1.5,  # 1.5x average = HVN
    lvn_threshold: float = 0.3   # 0.3x average = LVN
) -> Tuple[List[VolumeNode], List[VolumeNode]]:
    """Detect high and low volume nodes."""
    avg_volume = np.mean(volumes)

    hvn_levels = []
    lvn_levels = []

    # Look for local peaks (HVN) and valleys (LVN)
    for i in range(1, len(volumes) - 1):
        vol = volumes[i]
        price = price_levels[i]

        # Check if local maximum (HVN)
        if vol > volumes[i-1] and vol > volumes[i+1]:
            if vol > avg_volume * hvn_threshold:
                hvn_levels.append(VolumeNode(price, vol, "hvn"))

        # Check if local minimum (LVN)
        if vol < volumes[i-1] and vol < volumes[i+1]:
            if vol < avg_volume * lvn_threshold:
                lvn_levels.append(VolumeNode(price, vol, "lvn"))

    # Sort by volume (most significant first)
    hvn_levels.sort(key=lambda x: x.volume, reverse=True)
    lvn_levels.sort(key=lambda x: x.volume)

    return hvn_levels[:5], lvn_levels[:5]  # Top 5 each


def get_trade_location(
    current_price: float,
    profile: VolumeProfile,
    poc_tolerance: float = 2.0  # ticks
) -> TradeLocation:
    """
    Determine the trade location type for current price.

    Returns location type and score (0-25 for A+ system).
    """
    tick_size = profile.price_levels[1] - profile.price_levels[0]
    poc_distance = abs(current_price - profile.poc)
    fva_distance = min(
        abs(current_price - profile.fva_high),
        abs(current_price - profile.fva_low)
    )

    # Find nearest HVN/LVN
    nearest_hvn = None
    nearest_hvn_dist = float('inf')
    for hvn in profile.hvn_levels:
        dist = abs(current_price - hvn.price)
        if dist < nearest_hvn_dist:
            nearest_hvn = hvn.price
            nearest_hvn_dist = dist

    nearest_lvn = None
    nearest_lvn_dist = float('inf')
    for lvn in profile.lvn_levels:
        dist = abs(current_price - lvn.price)
        if dist < nearest_lvn_dist:
            nearest_lvn = lvn.price
            nearest_lvn_dist = dist

    # Determine location type and score
    if poc_distance <= poc_tolerance * tick_size:
        location_type = LocationType.POC
        score = 25  # Best location
    elif (profile.fva_low <= current_price <= profile.fva_high and
          fva_distance <= poc_tolerance * tick_size):
        location_type = LocationType.FVA_EDGE
        score = 20
    elif nearest_hvn_dist <= 3 * tick_size:
        location_type = LocationType.HVN
        score = 15
    elif nearest_lvn_dist <= 3 * tick_size:
        location_type = LocationType.LVN
        score = 18  # LVN breakouts can be good
    elif profile.value_area_low <= current_price <= profile.value_area_high:
        location_type = LocationType.VALUE_AREA
        score = 10
    else:
        location_type = LocationType.OUTSIDE
        score = 0

    return TradeLocation(
        location_type=location_type,
        price=current_price,
        distance_from_poc=poc_distance,
        distance_from_fva=fva_distance,
        nearest_hvn=nearest_hvn,
        nearest_lvn=nearest_lvn,
        score=score
    )


async def calculate_profile_for_symbol(
    symbol: str,
    timeframe: str = "1h",
    lookback_bars: int = 50,
    ohlcv_data: List[Dict] = None,
    config=None,
    **kwargs
) -> Dict:
    """
    High-level function to calculate profile for a symbol.
    Fetches data if not provided and returns profile as dict.
    """
    from tools.market_data import fetch_ohlcv

    logger.info(f"Calculating volume profile for {symbol}")

    # Use provided data or fetch it
    ohlcv = ohlcv_data or await fetch_ohlcv(symbol, timeframe, lookback_bars)

    if not ohlcv or len(ohlcv) < 10:
        return {'error': 'Insufficient data'}

    # Calculate profile
    profile = calculate_session_profile(ohlcv)

    return {
        'symbol': symbol,
        'poc': profile.poc,
        'fva_high': profile.fva_high,
        'fva_low': profile.fva_low,
        'value_area_high': profile.value_area_high,
        'value_area_low': profile.value_area_low,
        'hvn_levels': [{'price': h.price, 'volume': h.volume} for h in profile.hvn_levels],
        'lvn_levels': [{'price': l.price, 'volume': l.volume} for l in profile.lvn_levels],
        'total_volume': profile.total_volume
    }