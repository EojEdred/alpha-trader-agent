"""
Panda Forex API Adapter

For forex trading - AUTO execution mode.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import aiohttp


class PandaFXClient:
    """Panda Forex API client."""

    def __init__(self):
        self.api_key = os.getenv('PANDAFX_API_KEY')
        self.base_url = os.getenv('PANDAFX_BASE_URL', 'https://api.pandafx.com')
        self.username = os.getenv('PANDAFX_USERNAME')
        self.password = os.getenv('PANDAFX_PASSWORD')
        self.account_id = os.getenv('PANDAFX_ACCOUNT_ID')
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PandaFX/1.0",
            "Accept": "application/json"
        }

    async def authenticate(self) -> bool:
        """Authenticate with Panda FX API."""
        try:
            auth_data = {
                "username": self.username,
                "password": self.password
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/auth/login",
                    json=auth_data,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        token = data.get('access_token')
                        if token:
                            self.headers["Authorization"] = f"Bearer {token}"
                            return True
                        else:
                            logger.error("PandaFX: No access token in response")
                            return False
                    else:
                        logger.error(f"PandaFX authentication error: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"PandaFX authentication error: {e}")
            return False

    async def get_pairs(self) -> List[Dict]:
        """Get available currency pairs."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/pairs",
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('pairs', [])
                    else:
                        logger.error(f"PandaFX pairs error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"PandaFX pairs error: {e}")
            return []

    async def get_quotes(self, symbols: List[str] = None) -> Dict:
        """Get current quotes for currency pairs."""
        try:
            params = {}
            if symbols:
                params['symbols'] = ','.join(symbols)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/quotes",
                    params=params,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('quotes', {})
                    else:
                        logger.error(f"PandaFX quotes error: {resp.status}")
                        return {}
        except Exception as e:
            logger.error(f"PandaFX quotes error: {e}")
            return {}

    async def place_trade(self, pair: str, side: str, amount: float, 
                         order_type: str = "MARKET", price: float = None) -> Dict:
        """Place a forex trade."""
        logger.info(f"PandaFX: Attempting to place {side} trade for {amount} {pair}")

        try:
            trade_data = {
                "account_id": self.account_id,
                "symbol": pair,
                "side": side.upper(),  # BUY or SELL
                "amount": amount,
                "type": order_type.upper(),  # MARKET, LIMIT, STOP, etc.
            }
            
            if order_type.upper() != "MARKET" and price:
                trade_data["price"] = price

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/trades",
                    json=trade_data,
                    headers=self.headers
                ) as resp:
                    if resp.status in [200, 201]:
                        data = await resp.json()
                        return {
                            'status': 'success',
                            'trade_id': data.get('trade_id'),
                            'symbol': pair,
                            'side': side,
                            'amount': amount,
                            'price': data.get('price'),
                            'venue': 'PandaFX',
                            'executed_at': datetime.utcnow().isoformat()
                        }
                    else:
                        error_data = await resp.json()
                        logger.error(f"PandaFX trade error: {error_data}")
                        return {'error': error_data, 'status': 'failed'}
        except Exception as e:
            logger.error(f"PandaFX trade error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def get_positions(self) -> List[Dict]:
        """Get current forex positions."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/positions",
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        positions = []
                        
                        for pos in data.get('positions', []):
                            positions.append({
                                'venue': 'PandaFX',
                                'symbol': pos.get('symbol'),
                                'side': pos.get('side'),
                                'size': pos.get('size'),
                                'entry_price': pos.get('entry_price'),
                                'current_price': pos.get('current_price'),
                                'pnl': pos.get('pnl'),
                                'pnl_pct': pos.get('pnl_pct')
                            })
                        
                        return positions
                    else:
                        logger.error(f"PandaFX positions error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"PandaFX positions error: {e}")
            return []

    async def get_account_info(self) -> Dict:
        """Get account information."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/accounts/{self.account_id}",
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"PandaFX account info error: {resp.status}")
                        return {}
        except Exception as e:
            logger.error(f"PandaFX account info error: {e}")
            return {}


# Singleton
_pandafx_client = None


def get_pandafx_client() -> PandaFXClient:
    global _pandafx_client
    if _pandafx_client is None:
        _pandafx_client = PandaFXClient()
    return _pandafx_client


async def pandafx_get_pairs() -> Dict:
    """Fetch PandaFX currency pairs."""
    pairs = await get_pandafx_client().get_pairs()
    return {'pairs': pairs}


async def pandafx_get_quotes(symbols: List[str] = None) -> Dict:
    """Fetch PandaFX quotes."""
    quotes = await get_pandafx_client().get_quotes(symbols)
    return {'quotes': quotes}


async def pandafx_place_trade(pair: str, side: str, amount: float, 
                             order_type: str = "MARKET", price: float = None) -> Dict:
    """Place PandaFX trade."""
    return await get_pandafx_client().place_trade(pair, side, amount, order_type, price)


async def pandafx_get_positions() -> List[Dict]:
    """Get PandaFX positions."""
    return await get_pandafx_client().get_positions()


async def pandafx_get_account_info() -> Dict:
    """Get PandaFX account info."""
    return await get_pandafx_client().get_account_info()