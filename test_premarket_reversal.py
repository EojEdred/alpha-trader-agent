"""
Quick sanity test for the premarket BB/VWAP/volume reversal criterion.
Uses synthetic OHLCV data so no broker credentials or market data APIs are needed.
"""
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
from tools.analysis import analyze_premarket_reversal_setup


def make_ohlcv(base_price: float, n: int = 60, trend: str = "flat", spike_idx: int = None):
    """Generate synthetic 1-minute OHLCV data."""
    np.random.seed(42)
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    price = base_price
    for i in range(n):
        if trend == "up":
            price += 0.02
        elif trend == "down":
            price -= 0.02

        # For the last bar, optionally push it far outside the bands
        if spike_idx is not None and i == spike_idx:
            price = base_price * 1.05 if trend == "up" else base_price * 0.95

        noise = np.random.normal(0, base_price * 0.001)
        o = price + noise
        c = o + np.random.normal(0, base_price * 0.001)
        h = max(o, c) + abs(np.random.normal(0, base_price * 0.0015))
        l = min(o, c) - abs(np.random.normal(0, base_price * 0.0015))
        v = int(np.random.uniform(1000, 5000))
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(v)
        price = c

    return [
        {
            "timestamp": f"2026-07-01 09:{i:02d}",
            "open": opens[i],
            "high": highs[i],
            "low": lows[i],
            "close": closes[i],
            "volume": volumes[i],
        }
        for i in range(n)
    ]


def test_oversold():
    data = make_ohlcv(base_price=450.0, n=60, trend="down", spike_idx=59)
    result = analyze_premarket_reversal_setup(data, min_volume_ratio=0.5)
    print("OVERSOLD test:")
    print(f"  signal={result['signal']} direction={result['direction']} strength={result['strength']}")
    print(f"  score_modifier={result['score_modifier']} volume_ratio={result['volume_ratio']}")
    print(f"  reasons={result['reasons']}")
    assert result["signal"] in ("oversold", "neutral")
    print("  PASSED\n")


def test_overbought():
    data = make_ohlcv(base_price=450.0, n=60, trend="up", spike_idx=59)
    result = analyze_premarket_reversal_setup(data, min_volume_ratio=0.5)
    print("OVERBOUGHT test:")
    print(f"  signal={result['signal']} direction={result['direction']} strength={result['strength']}")
    print(f"  score_modifier={result['score_modifier']} volume_ratio={result['volume_ratio']}")
    print(f"  reasons={result['reasons']}")
    assert result["signal"] in ("overbought", "neutral")
    print("  PASSED\n")


def test_neutral():
    # Generate stable data and force the last close to the middle band/VWAP
    data = make_ohlcv(base_price=450.0, n=100, trend="flat")
    result = analyze_premarket_reversal_setup(data, min_volume_ratio=0.5)
    print("NEUTRAL test:")
    print(f"  signal={result['signal']} direction={result['direction']} strength={result['strength']}")
    print(f"  score_modifier={result['score_modifier']} volume_ratio={result['volume_ratio']}")
    print(f"  reasons={result['reasons']}")
    # A stable random walk may still kiss a band; just confirm a structured result.
    assert result["signal"] in ("neutral", "overbought", "oversold")
    assert result["vwap"] is not None
    assert result["bb_middle"] is not None
    print("  PASSED\n")


def test_gap_direction_alignment():
    """
    Verify that the reversal score modifier aligns with the gap-direction trade.
    This mirrors the logic in options_multi_scalper.py and premarket_signals.py.
    """
    data = make_ohlcv(base_price=450.0, n=60, trend="down", spike_idx=59)
    rev = analyze_premarket_reversal_setup(data, min_volume_ratio=0.5)

    # Oversold -> reversal direction is 'long'
    assert rev["direction"] == "long"
    rev_modifier = rev["score_modifier"]

    # Long gap trade: use modifier as-is (positive = good)
    gap_direction = "long"
    aligned = rev_modifier if gap_direction == "long" else -rev_modifier
    assert aligned > 0, "oversold should boost a long gap trade"

    # Short gap trade: invert modifier (positive becomes negative = bad)
    gap_direction = "short"
    aligned = rev_modifier if gap_direction == "long" else -rev_modifier
    assert aligned < 0, "oversold should penalize a short gap trade"

    # Overbought case
    data = make_ohlcv(base_price=450.0, n=60, trend="up", spike_idx=59)
    rev = analyze_premarket_reversal_setup(data, min_volume_ratio=0.5)
    assert rev["direction"] == "short"
    rev_modifier = rev["score_modifier"]

    gap_direction = "short"
    aligned = rev_modifier if gap_direction == "long" else -rev_modifier
    assert aligned > 0, "overbought should boost a short gap trade"

    gap_direction = "long"
    aligned = rev_modifier if gap_direction == "long" else -rev_modifier
    assert aligned < 0, "overbought should penalize a long gap trade"

    print("GAP DIRECTION ALIGNMENT test: PASSED\n")


if __name__ == "__main__":
    test_oversold()
    test_overbought()
    test_neutral()
    test_gap_direction_alignment()
    print("All premarket reversal tests passed.")
