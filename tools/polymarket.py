"""
Polymarket API Adapter

For prediction market trading - AUTO execution mode.
Only initializes the ccxt exchange when credentials are configured.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger


def _get_polymarket_exchange():
    """Lazy-load the ccxt Polymarket exchange if available and configured."""
    try:
        import ccxt
    except ImportError:
        raise RuntimeError("ccxt is not installed")

    exchange_cls = getattr(ccxt, 'polymarket', None)
    if exchange_cls is None:
        raise RuntimeError("ccxt.polymarket is not available in this ccxt version")

    api_key = os.getenv('POLYMARKET_API_KEY')
    secret = os.getenv('POLYMARKET_SECRET')
    if not api_key or not secret:
        raise RuntimeError("Polymarket credentials not configured")

    return exchange_cls({
        'apiKey': api_key,
        'secret': secret,
        'sandbox': True  # Use sandbox for testing
    })


class PolymarketClient:
    """Polymarket API client."""

    def __init__(self):
        self._exchange = None
        self._warned_once = False

    @property
    def is_configured(self) -> bool:
        return bool(os.getenv('POLYMARKET_API_KEY') and os.getenv('POLYMARKET_SECRET'))

    def _exchange_instance(self):
        if self._exchange is None:
            self._exchange = _get_polymarket_exchange()
        return self._exchange

    def _warn_if_unconfigured(self) -> None:
        if not self.is_configured and not self._warned_once:
            logger.warning(
                "Polymarket credentials not configured. "
                "Set POLYMARKET_API_KEY and POLYMARKET_SECRET in .env to enable Polymarket."
            )
            self._warned_once = True

    async def get_markets(self) -> List[Dict]:
        """Get available markets."""
        self._warn_if_unconfigured()
        if not self.is_configured:
            return []
        try:
            markets = self._exchange_instance().fetch_markets()
            return markets
        except Exception as e:
            logger.error(f"Polymarket markets error: {e}")
            return []

    async def get_positions(self) -> List[Dict]:
        """Get current positions."""
        self._warn_if_unconfigured()
        if not self.is_configured:
            return []
        try:
            positions = self._exchange_instance().fetch_positions()
            formatted_positions = []
            for pos in positions:
                formatted_positions.append({
                    'venue': 'Polymarket',
                    'symbol': pos.get('symbol', ''),
                    'side': pos.get('side', ''),
                    'size': pos.get('contracts', 0),
                    'entry': pos.get('entryPrice', 0),
                    'current': pos.get('markPrice', 0),
                    'pnl': pos.get('unrealizedPnl', 0)
                })
            return formatted_positions
        except Exception as e:
            logger.error(f"Polymarket positions error: {e}")
            return []

    async def place_order(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        size: float,
        price: float,
        order_type: str = "limit"
    ) -> Dict:
        """Place an order on Polymarket."""
        self._warn_if_unconfigured()
        if not self.is_configured:
            return {'error': 'Polymarket not configured', 'status': 'failed'}

        logger.info(f"Polymarket: Placing {side} order for {size} {symbol} @ {price}")

        try:
            order = self._exchange_instance().create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=size,
                price=price
            )

            return {
                'status': 'filled' if order.get('status') == 'closed' else 'pending',
                'order_id': order.get('id'),
                'symbol': symbol,
                'side': side,
                'size': size,
                'price': price,
                'venue': 'Polymarket',
                'executed_at': datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Polymarket order error: {e}")
            return {'error': str(e), 'status': 'failed'}


# Singleton
_poly_client = None


def get_poly_client() -> PolymarketClient:
    global _poly_client
    if _poly_client is None:
        _poly_client = PolymarketClient()
    return _poly_client


async def fetch_polymarket_markets() -> Dict:
    """Fetch Polymarket markets."""
    try:
        markets = await get_poly_client().get_markets()

        # Normalize to common format
        normalized = []
        for m in markets:
            if 'prediction' in m.get('symbol', '').lower():
                normalized.append({
                    'title': m.get('symbol', ''),
                    'ticker': m.get('id', ''),
                    'yes_price': m.get('last', 0.5),
                    'no_price': 1.0 - m.get('last', 0.5),
                    'volume': m.get('quoteVolume', 0)
                })

        return {'markets': normalized}
    except Exception as e:
        logger.error(f"Error fetching Polymarket markets: {e}")
        return {'markets': []}


async def place_order(**kwargs) -> Dict:
    return await get_poly_client().place_order(**kwargs)


async def polymarket_get_positions() -> List[Dict]:
    return await get_poly_client().get_positions()
