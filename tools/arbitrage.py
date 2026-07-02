"""
Arbitrage Scanner

Scans for prediction market arbitrage opportunities:
- Type A: Sum arbitrage (single platform)
- Type B: Cross-platform arbitrage
- Type C: Multi-outcome arbitrage
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime
from loguru import logger
import asyncio


@dataclass
class ArbOpportunity:
    type: str  # "sum", "cross_platform", "multi_outcome"
    market: str
    platforms: str
    spread_pct: float
    yes_price: float
    no_price: float
    liquidity: float
    expected_profit: float
    confidence: float
    valid: bool
    reason: str


async def scan_arbitrage(
    min_spread_pct: float = 1.0,
    max_results: int = 10,
    config=None,
    **kwargs
) -> List[ArbOpportunity]:
    """
    Scan all platforms for arbitrage opportunities.
    """
    logger.info(f"Scanning for arbitrage opportunities (min spread: {min_spread_pct}%)")

    opportunities = []

    # Scan each type
    sum_arbs = await _scan_sum_arbitrage(min_spread_pct)
    cross_arbs = await _scan_cross_platform_arbitrage(min_spread_pct)
    multi_arbs = await _scan_multi_outcome_arbitrage(min_spread_pct)

    opportunities.extend(sum_arbs)
    opportunities.extend(cross_arbs)
    opportunities.extend(multi_arbs)

    # Sort by spread (best first)
    opportunities.sort(key=lambda x: x.spread_pct, reverse=True)

    return opportunities[:max_results]


async def _scan_sum_arbitrage(min_spread_pct: float) -> List[ArbOpportunity]:
    """
    Type A: Sum arbitrage on single platform.

    Condition: YES_price + NO_price < $1.00 (minus fees)
    """
    opportunities = []

    # Scan Polymarket
    try:
        from tools.market_data import fetch_polymarket
        poly_data = await fetch_polymarket()

        for market in poly_data.get('markets', []):
            if not isinstance(market, dict):
                continue

            # Get YES/NO prices
            yes_price = market.get('yes_price', market.get('outcomePrices', [0.5])[0])
            no_price = market.get('no_price', 1 - yes_price if yes_price else 0.5)

            # Check for sum arb
            total = yes_price + no_price
            if total < 0.995:  # Account for ~0.5% fees
                spread_pct = (1.0 - total) * 100

                if spread_pct >= min_spread_pct:
                    opportunities.append(ArbOpportunity(
                        type="sum",
                        market=market.get('question', market.get('title', 'Unknown'))[:50],
                        platforms="Polymarket",
                        spread_pct=spread_pct,
                        yes_price=yes_price,
                        no_price=no_price,
                        liquidity=market.get('liquidity', 0),
                        expected_profit=spread_pct / 100,
                        confidence=0.9,
                        valid=True,
                        reason="Sum < 1.00"
                    ))
    except Exception as e:
        logger.error(f"Polymarket scan failed: {e}")

    # Scan Kalshi
    try:
        from tools.kalshi import fetch_kalshi_markets
        kalshi_data = await fetch_kalshi_markets()

        for market in kalshi_data.get('markets', []):
            yes_price = market.get('yes_price', 0.5)
            no_price = market.get('no_price', 0.5)

            total = yes_price + no_price
            if total < 0.995:
                spread_pct = (1.0 - total) * 100

                if spread_pct >= min_spread_pct:
                    opportunities.append(ArbOpportunity(
                        type="sum",
                        market=market.get('title', 'Unknown')[:50],
                        platforms="Kalshi",
                        spread_pct=spread_pct,
                        yes_price=yes_price,
                        no_price=no_price,
                        liquidity=market.get('volume', 0),
                        expected_profit=spread_pct / 100,
                        confidence=0.95,  # Kalshi is regulated
                        valid=True,
                        reason="Sum < 1.00"
                    ))
    except Exception as e:
        logger.error(f"Kalshi scan failed: {e}")

    return opportunities


async def _scan_cross_platform_arbitrage(min_spread_pct: float) -> List[ArbOpportunity]:
    """
    Type B: Cross-platform arbitrage.

    Condition: Platform1_YES + Platform2_NO < $1.00
    """
    opportunities = []

    # Need to match markets across platforms
    # This is complex - requires fuzzy matching of event descriptions

    try:
        from tools.market_data import fetch_polymarket
        from tools.kalshi import fetch_kalshi_markets

        poly_markets = await fetch_polymarket()
        kalshi_markets = await fetch_kalshi_markets()

        # Match markets by similar questions
        matched = _match_markets(
            poly_markets.get('markets', []),
            kalshi_markets.get('markets', [])
        )

        for match in matched:
            poly_yes = match['polymarket']['yes_price']
            kalshi_no = match['kalshi']['no_price']

            # Check Poly YES + Kalshi NO
            if poly_yes + kalshi_no < 0.985:  # Higher threshold for cross-platform
                spread_pct = (1.0 - poly_yes - kalshi_no) * 100

                if spread_pct >= min_spread_pct:
                    opportunities.append(ArbOpportunity(
                        type="cross_platform",
                        market=match['question'][:50],
                        platforms="Polymarket + Kalshi",
                        spread_pct=spread_pct,
                        yes_price=poly_yes,
                        no_price=kalshi_no,
                        liquidity=min(
                            match['polymarket'].get('liquidity', 0),
                            match['kalshi'].get('volume', 0)
                        ),
                        expected_profit=spread_pct / 100,
                        confidence=0.8,  # Lower due to resolution risk
                        valid=True,
                        reason="Cross-platform spread"
                    ))

            # Also check Kalshi YES + Poly NO
            kalshi_yes = match['kalshi']['yes_price']
            poly_no = match['polymarket']['no_price']

            if kalshi_yes + poly_no < 0.985:
                spread_pct = (1.0 - kalshi_yes - poly_no) * 100

                if spread_pct >= min_spread_pct:
                    opportunities.append(ArbOpportunity(
                        type="cross_platform",
                        market=match['question'][:50],
                        platforms="Kalshi + Polymarket",
                        spread_pct=spread_pct,
                        yes_price=kalshi_yes,
                        no_price=poly_no,
                        liquidity=min(
                            match['polymarket'].get('liquidity', 0),
                            match['kalshi'].get('volume', 0)
                        ),
                        expected_profit=spread_pct / 100,
                        confidence=0.8,
                        valid=True,
                        reason="Cross-platform spread"
                    ))

    except Exception as e:
        logger.error(f"Cross-platform scan failed: {e}")

    return opportunities


async def _scan_multi_outcome_arbitrage(min_spread_pct: float) -> List[ArbOpportunity]:
    """
    Type C: Multi-outcome arbitrage.

    Condition: Sum of all outcomes < $1.00
    """
    opportunities = []

    # For multi-outcome markets (e.g., "Who wins election?")
    # Sum all outcome prices - if < 1.00, buy all proportionally

    # Implementation depends on specific market structure
    # Placeholder for now

    return opportunities


def _match_markets(
    poly_markets: List[Dict],
    kalshi_markets: List[Dict]
) -> List[Dict]:
    """
    Match markets across platforms using fuzzy string matching.
    """
    matched = []

    # Simple keyword matching (would use better NLP in production)
    for poly in poly_markets:
        poly_q = str(poly.get('question', poly.get('title', ''))).lower()

        for kalshi in kalshi_markets:
            kalshi_q = str(kalshi.get('title', '')).lower()

            # Check for common keywords
            poly_words = set(poly_q.split())
            kalshi_words = set(kalshi_q.split())

            overlap = poly_words & kalshi_words
            # Filter out common words
            overlap -= {'will', 'the', 'be', 'in', 'on', 'by', 'a', 'an', 'to', 'of'}

            if len(overlap) >= 3:  # At least 3 meaningful words match
                matched.append({
                    'question': poly_q[:50],
                    'polymarket': {
                        'yes_price': poly.get('yes_price', 0.5),
                        'no_price': poly.get('no_price', 0.5),
                        'liquidity': poly.get('liquidity', 0)
                    },
                    'kalshi': {
                        'yes_price': kalshi.get('yes_price', 0.5),
                        'no_price': kalshi.get('no_price', 0.5),
                        'volume': kalshi.get('volume', 0)
                    }
                })

    return matched


async def execute_arbitrage(
    opportunity: ArbOpportunity,
    size: float,
    config=None
) -> Dict:
    """
    Execute an arbitrage trade.

    Places simultaneous orders on both sides.
    """
    logger.info(f"Executing {opportunity.type} arb: {opportunity.market}")

    results = {
        'opportunity': opportunity,
        'size': size,
        'orders': [],
        'status': 'pending',
        'executed_at': datetime.utcnow().isoformat()
    }

    # Execute based on type
    if opportunity.type == "sum":
        # Buy both YES and NO on same platform
        platform = opportunity.platforms.lower()

        if 'polymarket' in platform:
            from tools.polymarket import place_order as poly_order

            yes_order = await poly_order(
                market=opportunity.market,
                side='yes',
                size=size,
                price=opportunity.yes_price
            )
            no_order = await poly_order(
                market=opportunity.market,
                side='no',
                size=size,
                price=opportunity.no_price
            )

            results['orders'] = [yes_order, no_order]

    elif opportunity.type == "cross_platform":
        # Buy on different platforms simultaneously
        from tools.polymarket import place_order as poly_order
        from tools.kalshi import place_order as kalshi_order

        # Execute both in parallel
        orders = await asyncio.gather(
            poly_order(
                market=opportunity.market,
                side='yes',
                size=size,
                price=opportunity.yes_price
            ),
            kalshi_order(
                market=opportunity.market,
                side='no',
                size=size,
                price=opportunity.no_price
            ),
            return_exceptions=True
        )

        results['orders'] = orders

    # Check if both filled
    all_filled = all(
        o.get('status') == 'filled'
        for o in results['orders']
        if isinstance(o, dict)
    )

    results['status'] = 'filled' if all_filled else 'partial'

    return results