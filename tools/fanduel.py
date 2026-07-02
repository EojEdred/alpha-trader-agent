"""
FanDuel API Adapter

For sports betting and DFS - AUTO execution mode.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import aiohttp


class FanDuelClient:
    """FanDuel API client."""

    BASE_URL = "https://probets.fanduel.com"
    GRAPHQL_URL = "https://probets.fanduel.com/graphql"
    MARKETS_URL = "https://probets.fanduel.com/markets"

    def __init__(self):
        self.api_key = os.getenv('FANDUEL_API_KEY')
        self.access_token = os.getenv('FANDUEL_ACCESS_TOKEN')
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "x-fd-us-east-api-key": self.api_key,
            "User-Agent": "FanDuel/17.10.0 (iPhone; iOS 16.5; Scale/3.00)",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json"
        }

    async def get_sports(self) -> List[Dict]:
        """Get available sports."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.MARKETS_URL}/sports",
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('sports', [])
                    else:
                        logger.error(f"FanDuel sports error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"FanDuel sports error: {e}")
            return []

    async def get_events(self, sport_id: str) -> List[Dict]:
        """Get events for a specific sport."""
        try:
            params = {
                "sportId": sport_id,
                "preMatchOnly": "true"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.MARKETS_URL}/events",
                    params=params,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('events', [])
                    else:
                        logger.error(f"FanDuel events error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"FanDuel events error: {e}")
            return []

    async def get_markets(self, event_id: str) -> List[Dict]:
        """Get available markets for an event."""
        try:
            params = {
                "eventId": event_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.MARKETS_URL}/markets",
                    params=params,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('markets', [])
                    else:
                        logger.error(f"FanDuel markets error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"FanDuel markets error: {e}")
            return []

    async def place_bet(self, bet_data: Dict) -> Dict:
        """Place a bet."""
        logger.info(f"FanDuel: Attempting to place bet")

        try:
            # In a real implementation, this would make the actual bet placement API call
            # For now, we'll simulate the bet
            bet_request = {
                'bet_data': bet_data,
                'placed_at': datetime.utcnow().isoformat()
            }
            
            return {
                'status': 'simulated',
                'bet_id': f"BET_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                'bet_data': bet_data,
                'venue': 'FanDuel',
                'executed_at': datetime.utcnow().isoformat(),
                'note': 'Simulated - Actual API integration needed'
            }
        except Exception as e:
            logger.error(f"FanDuel bet placement error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def get_positions(self) -> List[Dict]:
        """Get current bets."""
        try:
            # This would require user authentication and access to their bets
            # For now, return empty as we don't have user-specific access
            logger.info("FanDuel: Getting current bets - requires user authentication")
            
            return []
        except Exception as e:
            logger.error(f"FanDuel positions error: {e}")
            return []


# Singleton
_fanduel_client = None


def get_fanduel_client() -> FanDuelClient:
    global _fanduel_client
    if _fanduel_client is None:
        _fanduel_client = FanDuelClient()
    return _fanduel_client


async def fanduel_get_sports() -> Dict:
    """Fetch FanDuel sports."""
    sports = await get_fanduel_client().get_sports()
    return {'sports': sports}


async def fanduel_get_events(sport_id: str) -> Dict:
    """Fetch FanDuel events for a sport."""
    events = await get_fanduel_client().get_events(sport_id)
    return {'events': events}


async def fanduel_get_markets(event_id: str) -> Dict:
    """Fetch FanDuel markets for an event."""
    markets = await get_fanduel_client().get_markets(event_id)
    return {'markets': markets}


async def fanduel_place_bet(bet_data: Dict) -> Dict:
    """Place FanDuel bet."""
    return await get_fanduel_client().place_bet(bet_data)


async def fanduel_get_positions() -> List[Dict]:
    """Get FanDuel positions."""
    return await get_fanduel_client().get_positions()