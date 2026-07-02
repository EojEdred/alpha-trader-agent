"""
PrizePicks API Adapter

For sports betting and contest trading - AUTO execution mode.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import aiohttp


class PrizePicksClient:
    """PrizePicks API client."""

    BASE_URL = "https://api.prizepicks.com"
    GRAPHQL_URL = "https://api.prizepicks.com/graphql"

    def __init__(self):
        self.api_key = os.getenv('PRIZEPICKS_API_KEY')
        self.session_token = os.getenv('PRIZEPICKS_SESSION_TOKEN')
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PrizePicks/4.23.0 (iPhone; iOS 16.5; Scale/3.00)",
            "Accept": "application/vnd.api+json",
            "Accept-Language": "en-US,en;q=0.9"
        }

    async def get_projections(self, league_ids: List[str] = None) -> List[Dict]:
        """Get available projections."""
        try:
            params = {
                "sport[league_ids][]": league_ids or [],
                "stat_type[category]": "All Scoring",
                "single_stat": "true"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/projections",
                    params=params,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        projections = []
                        for item in data.get('data', []):
                            attributes = item.get('attributes', {})
                            
                            projections.append({
                                'id': item.get('id'),
                                'player_name': attributes.get('player_name'),
                                'team': attributes.get('team'),
                                'opponent': attributes.get('opponent'),
                                'league': attributes.get('league_name'),
                                'stat_type': attributes.get('stat_type'),
                                'projection': attributes.get('line_score'),
                                'updated_at': attributes.get('updated_at'),
                                'game_start_time': attributes.get('game_start_time')
                            })
                        
                        return projections
                    else:
                        logger.error(f"PrizePicks projections error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"PrizePicks projections error: {e}")
            return []

    async def get_leagues(self) -> List[Dict]:
        """Get available leagues."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/leagues",
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        leagues = []
                        for item in data.get('data', []):
                            attributes = item.get('attributes', {})
                            leagues.append({
                                'id': item.get('id'),
                                'name': attributes.get('name'),
                                'abbreviation': attributes.get('abbreviation')
                            })
                        
                        return leagues
                    else:
                        logger.error(f"PrizePicks leagues error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"PrizePicks leagues error: {e}")
            return []

    async def get_contest_types(self) -> List[Dict]:
        """Get available contest types."""
        try:
            query = """
            query ContestTypes($per_page: Int) {
                contestTypes(per_page: $per_page) {
                    id
                    name
                    game_type
                    entry_fee
                    payout
                    start_time
                    end_time
                    status
                }
            }
            """
            
            payload = {
                "query": query,
                "variables": {"per_page": 50}
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.GRAPHQL_URL,
                    json=payload,
                    headers=self.headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        if 'data' in data and 'contestTypes' in data['data']:
                            return data['data']['contestTypes']
                        else:
                            return []
                    else:
                        logger.error(f"PrizePicks contest types error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"PrizePicks contest types error: {e}")
            return []

    async def get_active_contests(self) -> List[Dict]:
        """Get active contests."""
        try:
            # First get contest types
            contest_types = await self.get_contest_types()
            
            # Filter for active contests
            active_contests = []
            for ct in contest_types:
                if ct.get('status') == 'active':
                    active_contests.append(ct)
            
            return active_contests
        except Exception as e:
            logger.error(f"PrizePicks active contests error: {e}")
            return []

    async def place_entry(self, contest_id: str, player_selections: List[Dict]) -> Dict:
        """Place an entry in a contest."""
        logger.info(f"PrizePicks: Attempting to place entry in contest {contest_id}")

        try:
            # This would require more detailed implementation based on actual API
            # For now, we'll simulate the entry
            entry_data = {
                'contest_id': contest_id,
                'selections': player_selections,
                'placed_at': datetime.utcnow().isoformat()
            }
            
            # In a real implementation, this would make the actual API call
            # to submit the entry to PrizePicks
            
            return {
                'status': 'simulated',
                'entry_id': f"ENTRY_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                'contest_id': contest_id,
                'selections': player_selections,
                'venue': 'PrizePicks',
                'executed_at': datetime.utcnow().isoformat(),
                'note': 'Simulated - Actual API integration needed'
            }
        except Exception as e:
            logger.error(f"PrizePicks entry error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def get_positions(self) -> List[Dict]:
        """Get current positions/entries."""
        try:
            # This would require user authentication and access to their entries
            # For now, return empty as we don't have user-specific access
            logger.info("PrizePicks: Getting current positions - requires user authentication")
            
            return []
        except Exception as e:
            logger.error(f"PrizePicks positions error: {e}")
            return []


# Singleton
_prizepicks_client = None


def get_prizepicks_client() -> PrizePicksClient:
    global _prizepicks_client
    if _prizepicks_client is None:
        _prizepicks_client = PrizePicksClient()
    return _prizepicks_client


async def prizepicks_get_projections(league_ids: List[str] = None) -> Dict:
    """Fetch PrizePicks projections."""
    projections = await get_prizepicks_client().get_projections(league_ids)
    return {'projections': projections}


async def prizepicks_get_leagues() -> Dict:
    """Fetch PrizePicks leagues."""
    leagues = await get_prizepicks_client().get_leagues()
    return {'leagues': leagues}


async def prizepicks_get_contests() -> Dict:
    """Fetch PrizePicks contests."""
    contests = await get_prizepicks_client().get_active_contests()
    return {'contests': contests}


async def prizepicks_place_entry(contest_id: str, player_selections: List[Dict]) -> Dict:
    """Place PrizePicks entry."""
    return await get_prizepicks_client().place_entry(contest_id, player_selections)


async def prizepicks_get_positions() -> List[Dict]:
    """Get PrizePicks positions."""
    return await get_prizepicks_client().get_positions()