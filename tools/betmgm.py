"""
BetMGM API Adapter

For sports betting - AUTO execution mode.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import aiohttp


class BetMGMClient:
    """BetMGM API client."""

    BASE_URL = "https://sports.betmgm.com"
    LINE_VIEW_URL = "https://sports.betmgm.com/integrated/api/ngintegration/sports-offering/line-view"
    CUSTOMER_URL = "https://customers.betmgm.com/api/v1/customer"
    BET_URL = "https://bets.betmgm.com/bets/api/v1/bets"

    def __init__(self):
        self.api_key = os.getenv('BETMGM_API_KEY')
        self.customer_id = os.getenv('BETMGM_CUSTOMER_ID')
        self.session_token = os.getenv('BETMGM_SESSION_TOKEN')
        self.headers = {
            "x-api-key": self.api_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://sports.betmgm.com/",
            "Origin": "https://sports.betmgm.com"
        }

    async def get_sports(self) -> List[Dict]:
        """Get available sports."""
        try:
            params = {
                "configId": "1",
                "competitionId": "0",
                "preMatchOnly": "true",
                "section": "All Sports",
                "tab": "popular"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.LINE_VIEW_URL}/sports",
                    params=params,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('sports', [])
                    else:
                        logger.error(f"BetMGM sports error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"BetMGM sports error: {e}")
            return []

    async def get_events(self, sport_id: str) -> List[Dict]:
        """Get events for a specific sport."""
        try:
            params = {
                "configId": "1",
                "competitionId": "0",
                "preMatchOnly": "true",
                "section": "All Sports",
                "tab": "popular",
                "sportId": sport_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.LINE_VIEW_URL}/events",
                    params=params,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('events', [])
                    else:
                        logger.error(f"BetMGM events error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"BetMGM events error: {e}")
            return []

    async def get_markets(self, event_id: str) -> List[Dict]:
        """Get available markets for an event."""
        try:
            params = {
                "configId": "1",
                "eventIds": event_id,
                "includeLiveOdds": "false",
                "preMatchOnly": "true",
                "section": "All Sports",
                "tab": "popular"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.LINE_VIEW_URL}/markets",
                    params=params,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('markets', [])
                    else:
                        logger.error(f"BetMGM markets error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"BetMGM markets error: {e}")
            return []

    async def place_bet(self, bet_data: Dict) -> Dict:
        """Place a bet."""
        logger.info(f"BetMGM: Attempting to place bet")

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
                'venue': 'BetMGM',
                'executed_at': datetime.utcnow().isoformat(),
                'note': 'Simulated - Actual API integration needed'
            }
        except Exception as e:
            logger.error(f"BetMGM bet placement error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def get_positions(self) -> List[Dict]:
        """Get current bets."""
        try:
            # This would require customer authentication and access to their bets
            # For now, return empty as we don't have user-specific access
            logger.info("BetMGM: Getting current bets - requires user authentication")
            
            return []
        except Exception as e:
            logger.error(f"BetMGM positions error: {e}")
            return []


# Singleton
_betmgm_client = None


def get_betmgm_client() -> BetMGMClient:
    global _betmgm_client
    if _betmgm_client is None:
        _betmgm_client = BetMGMClient()
    return _betmgm_client


async def betmgm_get_sports() -> Dict:
    """Fetch BetMGM sports."""
    sports = await get_betmgm_client().get_sports()
    return {'sports': sports}


async def betmgm_get_events(sport_id: str) -> Dict:
    """Fetch BetMGM events for a sport."""
    events = await get_betmgm_client().get_events(sport_id)
    return {'events': events}


async def betmgm_get_markets(event_id: str) -> Dict:
    """Fetch BetMGM markets for an event."""
    markets = await get_betmgm_client().get_markets(event_id)
    return {'markets': markets}


async def betmgm_place_bet(bet_data: Dict) -> Dict:
    """Place BetMGM bet."""
    return await get_betmgm_client().place_bet(bet_data)


async def betmgm_get_positions() -> List[Dict]:
    """Get BetMGM positions."""
    return await get_betmgm_client().get_positions()