"""
Per-Venue Rate Limiter

Token bucket algorithm for preventing rapid-fire execution
that could trigger IP bans or account suspensions.
"""

import time
import asyncio
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from loguru import logger


@dataclass
class RateLimit:
    """Rate limit configuration for a venue."""
    max_requests: int  # Max requests in the window
    window_seconds: int  # Time window
    min_interval_seconds: float  # Minimum seconds between requests


# Default rate limits per venue
DEFAULT_LIMITS: Dict[str, RateLimit] = {
    "oanda": RateLimit(max_requests=30, window_seconds=60, min_interval_seconds=1.0),
    "schwab": RateLimit(max_requests=10, window_seconds=60, min_interval_seconds=2.0),
    "kalshi": RateLimit(max_requests=20, window_seconds=60, min_interval_seconds=1.0),
    "polymarket": RateLimit(max_requests=15, window_seconds=60, min_interval_seconds=1.0),
    "topstep": RateLimit(max_requests=12, window_seconds=60, min_interval_seconds=5.0),
    "apex": RateLimit(max_requests=12, window_seconds=60, min_interval_seconds=5.0),
    "tradingview": RateLimit(max_requests=20, window_seconds=60, min_interval_seconds=2.0),
    "thinkorswim": RateLimit(max_requests=30, window_seconds=60, min_interval_seconds=1.0),
    "tradovate": RateLimit(max_requests=30, window_seconds=60, min_interval_seconds=1.0),
}


class RateLimiter:
    """
    Token bucket rate limiter per venue.
    
    Usage:
        limiter = RateLimiter()
        if await limiter.check_and_wait("oanda"):
            # Execute trade
        else:
            # Rate limited, reject or queue
    """
    
    def __init__(self, limits: Optional[Dict[str, RateLimit]] = None):
        self.limits = limits or DEFAULT_LIMITS
        # State: venue -> {"tokens": float, "last_update": timestamp, "request_times": [timestamps]}
        self._state: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
    
    async def check_and_wait(self, venue: str, wait: bool = True) -> bool:
        """
        Check if request is allowed for venue. Optionally wait until allowed.
        
        Args:
            venue: The venue to check
            wait: If True, block until request is allowed. If False, return immediately.
        
        Returns:
            True if request is (or becomes) allowed, False if rate limited.
        """
        venue = venue.lower()
        limit = self.limits.get(venue)
        if not limit:
            # No limit configured = allow
            return True
        
        async with self._lock:
            now = time.time()
            
            if venue not in self._state:
                self._state[venue] = {
                    "tokens": limit.max_requests,
                    "last_update": now,
                    "request_times": [],
                }
            
            state = self._state[venue]
            
            # Remove old request times outside window
            cutoff = now - limit.window_seconds
            state["request_times"] = [t for t in state["request_times"] if t > cutoff]
            
            # Check window limit
            if len(state["request_times"]) >= limit.max_requests:
                if not wait:
                    logger.warning(f"Rate limited: {venue} exceeded {limit.max_requests} requests in {limit.window_seconds}s")
                    return False
                
                # Wait until oldest request falls out of window
                oldest = state["request_times"][0]
                sleep_time = oldest + limit.window_seconds - now + 0.1
                logger.info(f"Rate limit: waiting {sleep_time:.1f}s for {venue}")
                await asyncio.sleep(sleep_time)
                return await self.check_and_wait(venue, wait=True)
            
            # Check minimum interval
            if state["request_times"]:
                last_request = state["request_times"][-1]
                elapsed = now - last_request
                if elapsed < limit.min_interval_seconds:
                    if not wait:
                        logger.warning(f"Rate limited: {venue} minimum interval {limit.min_interval_seconds}s not met")
                        return False
                    
                    sleep_time = limit.min_interval_seconds - elapsed + 0.1
                    logger.info(f"Rate limit: waiting {sleep_time:.1f}s for {venue} min interval")
                    await asyncio.sleep(sleep_time)
                    return await self.check_and_wait(venue, wait=True)
            
            # Allow request
            state["request_times"].append(time.time())
            return True
    
    async def acquire(self, venue: str) -> bool:
        """Non-blocking check. Returns True if allowed, False if rate limited."""
        return await self.check_and_wait(venue, wait=False)
    
    def get_status(self, venue: str) -> Dict:
        """Get current rate limit status for a venue."""
        venue = venue.lower()
        state = self._state.get(venue, {"request_times": []})
        limit = self.limits.get(venue)
        
        now = time.time()
        cutoff = now - limit.window_seconds if limit else now
        recent = [t for t in state["request_times"] if t > cutoff]
        
        return {
            "venue": venue,
            "recent_requests": len(recent),
            "max_requests": limit.max_requests if limit else None,
            "window_seconds": limit.window_seconds if limit else None,
            "remaining": (limit.max_requests - len(recent)) if limit else None,
            "limited": len(recent) >= limit.max_requests if limit else False,
        }
