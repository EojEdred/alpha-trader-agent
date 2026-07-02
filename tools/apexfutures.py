"""
Apex Funded Futures API Adapter

For funded futures trading - AUTO execution mode.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import aiohttp


class ApexFuturesClient:
    """Apex Funded Futures API client."""

    def __init__(self):
        self.api_key = os.getenv('APEXFUTURES_API_KEY')
        self.base_url = os.getenv('APEXFUTURES_BASE_URL', 'https://api.apexfutures.com')
        self.username = os.getenv('APEXFUTURES_USERNAME')
        self.password = os.getenv('APEXFUTURES_PASSWORD')
        self.account_id = os.getenv('APEXFUTURES_ACCOUNT_ID')
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ApexFutures/1.0",
            "Accept": "application/json"
        }

    async def authenticate(self) -> bool:
        """Authenticate with Apex Futures API."""
        try:
            auth_data = {
                "username": self.username,
                "password": self.password,
                "account_id": self.account_id
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
                            logger.error("ApexFutures: No access token in response")
                            return False
                    else:
                        logger.error(f"ApexFutures authentication error: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"ApexFutures authentication error: {e}")
            return False

    async def get_contracts(self) -> List[Dict]:
        """Get available futures contracts."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/contracts",
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('contracts', [])
                    else:
                        logger.error(f"ApexFutures contracts error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"ApexFutures contracts error: {e}")
            return []

    async def get_quotes(self, symbols: List[str] = None) -> Dict:
        """Get current quotes for futures contracts."""
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
                        logger.error(f"ApexFutures quotes error: {resp.status}")
                        return {}
        except Exception as e:
            logger.error(f"ApexFutures quotes error: {e}")
            return {}

    async def place_trade(self, symbol: str, side: str, quantity: int, 
                         order_type: str = "MARKET", price: float = None) -> Dict:
        """Place a futures trade."""
        logger.info(f"ApexFutures: Attempting to place {side} trade for {quantity} {symbol}")

        try:
            trade_data = {
                "account_id": self.account_id,
                "symbol": symbol,
                "side": side.upper(),  # BUY or SELL
                "quantity": quantity,
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
                            'symbol': symbol,
                            'side': side,
                            'quantity': quantity,
                            'price': data.get('price'),
                            'venue': 'ApexFutures',
                            'executed_at': datetime.utcnow().isoformat()
                        }
                    else:
                        error_data = await resp.json()
                        logger.error(f"ApexFutures trade error: {error_data}")
                        return {'error': error_data, 'status': 'failed'}
        except Exception as e:
            logger.error(f"ApexFutures trade error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def get_positions(self) -> List[Dict]:
        """Get current futures positions."""
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
                                'venue': 'ApexFutures',
                                'symbol': pos.get('symbol'),
                                'side': pos.get('side'),
                                'quantity': pos.get('quantity'),
                                'entry_price': pos.get('entry_price'),
                                'current_price': pos.get('current_price'),
                                'pnl': pos.get('pnl'),
                                'pnl_pct': pos.get('pnl_pct')
                            })
                        
                        return positions
                    else:
                        logger.error(f"ApexFutures positions error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"ApexFutures positions error: {e}")
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
                        logger.error(f"ApexFutures account info error: {resp.status}")
                        return {}
        except Exception as e:
            logger.error(f"ApexFutures account info error: {e}")
            return {}

    async def get_pnl_summary(self) -> Dict:
        """Get P&L summary for the account."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/pnl",
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"ApexFutures P&L summary error: {resp.status}")
                        return {}
        except Exception as e:
            logger.error(f"ApexFutures P&L summary error: {e}")
            return {}


# Singleton
_apexfutures_client = None


def get_apexfutures_client() -> ApexFuturesClient:
    global _apexfutures_client
    if _apexfutures_client is None:
        _apexfutures_client = ApexFuturesClient()
    return _apexfutures_client


async def apexfutures_get_contracts() -> Dict:
    """Fetch ApexFutures contracts."""
    contracts = await get_apexfutures_client().get_contracts()
    return {'contracts': contracts}


async def apexfutures_get_quotes(symbols: List[str] = None) -> Dict:
    """Fetch ApexFutures quotes."""
    quotes = await get_apexfutures_client().get_quotes(symbols)
    return {'quotes': quotes}


async def apexfutures_place_trade(symbol: str, side: str, quantity: int, 
                                 order_type: str = "MARKET", price: float = None) -> Dict:
    """Place ApexFutures trade."""
    return await get_apexfutures_client().place_trade(symbol, side, quantity, order_type, price)


async def apexfutures_get_positions() -> List[Dict]:
    """Get ApexFutures positions."""
    return await get_apexfutures_client().get_positions()


async def apexfutures_get_account_info() -> Dict:
    """Get ApexFutures account info."""
    return await get_apexfutures_client().get_account_info()


async def apexfutures_get_pnl_summary() -> Dict:
    """Get ApexFutures P&L summary."""
    return await get_apexfutures_client().get_pnl_summary()