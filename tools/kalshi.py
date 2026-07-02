"""
Kalshi API Adapter

For regulated prediction market trading - AUTO execution mode.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import aiohttp


class KalshiClient:
    """Kalshi API client."""

    BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"

    def __init__(self):
        self.email = os.getenv('KALSHI_EMAIL')
        self.password = os.getenv('KALSHI_PASSWORD')
        self.token = None

    async def _ensure_authenticated(self):
        """Ensure we have a valid auth token."""
        if self.token:
            return True

        if not self.email or not self.password:
            logger.warning("Kalshi credentials not configured")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.BASE_URL}/login",
                    json={"email": self.email, "password": self.password}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.token = data.get('token')
                        return True
                    else:
                        logger.error(f"Kalshi login failed: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Kalshi auth error: {e}")
            return False

    def _headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self.token}" if self.token else "",
            "Content-Type": "application/json"
        }

    async def get_markets(self, status: str = "open") -> List[Dict]:
        """Get available markets."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/markets",
                    params={"status": status},
                    headers=self._headers()
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('markets', [])
                    return []
        except Exception as e:
            logger.error(f"Kalshi markets error: {e}")
            return []

    async def get_positions(self) -> List[Dict]:
        """Get current positions."""
        if not await self._ensure_authenticated():
            return []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/portfolio/positions",
                    headers=self._headers()
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        positions = []
                        for pos in data.get('market_positions', []):
                            positions.append({
                                'venue': 'Kalshi',
                                'symbol': pos.get('ticker', ''),
                                'side': 'yes' if pos.get('position', 0) > 0 else 'no',
                                'size': abs(pos.get('position', 0)),
                                'entry': pos.get('average_price', 0),
                                'current': pos.get('market_price', 0),
                                'pnl': pos.get('unrealized_pnl', 0)
                            })
                        return positions
                    return []
        except Exception as e:
            logger.error(f"Kalshi positions error: {e}")
            return []

    async def place_order(
        self,
        ticker: str,
        side: str,  # "yes" or "no"
        size: int,
        price: float,  # 0.01 to 0.99
        order_type: str = "limit"
    ) -> Dict:
        """Place an order on Kalshi."""
        if not await self._ensure_authenticated():
            return {'error': 'Not authenticated', 'status': 'failed'}

        logger.info(f"Kalshi: Placing {side} order for {size} contracts on {ticker} @ {price}")

        try:
            order_data = {
                "ticker": ticker,
                "action": "buy",  # Always buy, side determines yes/no
                "side": side,
                "count": size,
                "type": order_type
            }

            if order_type == "limit":
                order_data["yes_price"] = int(price * 100) if side == "yes" else None
                order_data["no_price"] = int(price * 100) if side == "no" else None

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.BASE_URL}/portfolio/orders",
                    json=order_data,
                    headers=self._headers()
                ) as resp:
                    if resp.status in [200, 201]:
                        data = await resp.json()
                        return {
                            'status': 'filled' if data.get('order', {}).get('status') == 'executed' else 'pending',
                            'order_id': data.get('order', {}).get('order_id'),
                            'ticker': ticker,
                            'side': side,
                            'size': size,
                            'price': price,
                            'venue': 'Kalshi',
                            'executed_at': datetime.utcnow().isoformat()
                        }
                    else:
                        error = await resp.text()
                        return {'error': error, 'status': 'failed'}

        except Exception as e:
            logger.error(f"Kalshi order error: {e}")
            return {'error': str(e), 'status': 'failed'}


# Singleton
_kalshi_client = None


def get_kalshi_client() -> KalshiClient:
    global _kalshi_client
    if _kalshi_client is None:
        _kalshi_client = KalshiClient()
    return _kalshi_client


async def fetch_kalshi_markets() -> Dict:
    """Fetch Kalshi markets."""
    markets = await get_kalshi_client().get_markets()

    # Normalize to common format
    normalized = []
    for m in markets:
        normalized.append({
            'title': m.get('title', ''),
            'ticker': m.get('ticker', ''),
            'yes_price': m.get('yes_price', 50) / 100,  # Convert cents to dollars
            'no_price': m.get('no_price', 50) / 100,
            'volume': m.get('volume', 0)
        })

    return {'markets': normalized}


async def place_order(**kwargs) -> Dict:
    return await get_kalshi_client().place_order(**kwargs)


async def kalshi_get_positions() -> List[Dict]:
    return await get_kalshi_client().get_positions()