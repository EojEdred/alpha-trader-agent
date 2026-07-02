"""
Market Data Cache Layer

In-memory caching with TTL, hit tracking, and source reliability weighting.
"""

import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from loguru import logger
import hashlib
import json


class CacheEntry:
    """Single cache entry with metadata."""

    def __init__(
        self, key: str, data: Dict[str, Any], source: str, ttl_seconds: int = 300
    ):
        self.key = key
        self.data = data
        self.source = source
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(seconds=ttl_seconds)
        self.hits = 0
        self.last_hit = None

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return datetime.utcnow() > self.expires_at

    def record_hit(self):
        """Record a cache hit."""
        self.hits += 1
        self.last_hit = datetime.utcnow()

    def age_seconds(self) -> int:
        """Get age in seconds."""
        return int((datetime.utcnow() - self.created_at).total_seconds())


class MarketDataCache:
    """
    In-memory cache for market data.

    Features:
    - TTL (time-to-live) with automatic expiration
    - Hit tracking for source reliability
    - Source weighting based on hit rate
    - Cache statistics
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.cache: Dict[str, CacheEntry] = {}

        cache_config = self.config.get("cache", {})
        self.default_ttl = cache_config.get("default_ttl_seconds", 300)  # 5 minutes
        self.max_size = cache_config.get("max_size", 1000)  # Max entries
        self.enabled = cache_config.get("enabled", True)

        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "evictions": 0,
        }

    def generate_key(self, symbol: str, data_type: str, provider: str, **kwargs) -> str:
        """
        Generate unique cache key.

        Args:
            symbol: SPY, QQQ, etc.
            data_type: 'technical', 'fundamentals', 'news', 'options_flow'
            provider: 'oanda', 'alphavantage', 'newsapi', 'polygon'
            **kwargs: Additional parameters (timeframe, granularity, etc.)

        Returns:
            Unique cache key string
        """
        params_str = json.dumps(kwargs, sort_keys=True)
        key_string = f"{data_type}:{provider}:{symbol}:{params_str}"

        return hashlib.md5(key_string.encode()).hexdigest()

    async def get(
        self, symbol: str, data_type: str, provider: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Get data from cache.

        Args:
            symbol: Trading symbol
            data_type: Type of data
            provider: Data provider
            **kwargs: Additional parameters

        Returns:
            Cached data dict or None if not found/expired
        """
        if not self.enabled:
            return None

        self.stats["total_requests"] += 1

        key = self.generate_key(symbol, data_type, provider, **kwargs)

        if key not in self.cache:
            self.stats["cache_misses"] += 1
            logger.debug(f"Cache miss: {key}")
            return None

        entry = self.cache[key]

        if entry.is_expired():
            del self.cache[key]
            self.stats["cache_misses"] += 1
            self.stats["evictions"] += 1
            logger.debug(f"Cache expired and evicted: {key}")
            return None

        entry.record_hit()
        self.stats["cache_hits"] += 1

        logger.info(
            f"Cache hit: {key} (hits: {entry.hits}, age: {entry.age_seconds()}s)"
        )

        return {
            "data": entry.data,
            "source": entry.source,
            "cached_at": entry.created_at.isoformat(),
            "hits": entry.hits,
        }

    async def set(
        self,
        symbol: str,
        data_type: str,
        provider: str,
        data: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
        **kwargs,
    ) -> bool:
        """
        Store data in cache.

        Args:
            symbol: Trading symbol
            data_type: Type of data
            provider: Data provider
            data: Data to cache
            ttl_seconds: Time-to-live in seconds (uses default if None)
            **kwargs: Additional parameters

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        key = self.generate_key(symbol, data_type, provider, **kwargs)

        if len(self.cache) >= self.max_size:
            self._evict_oldest()

        ttl = ttl_seconds or self.default_ttl

        entry = CacheEntry(key=key, data=data, source=provider, ttl_seconds=ttl)

        self.cache[key] = entry

        logger.info(
            f"Cached: {key} (TTL: {ttl}s, size: {len(self.cache)}/{self.max_size})"
        )

        return True

    async def get_or_fetch(
        self,
        symbol: str,
        data_type: str,
        provider: str,
        fetch_func: callable,
        ttl_seconds: Optional[int] = None,
        **kwargs,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Get from cache or fetch if not available.

        Args:
            symbol: Trading symbol
            data_type: Type of data
            provider: Data provider
            fetch_func: Async function to fetch data
            ttl_seconds: Time-to-live
            **kwargs: Additional parameters for fetch_func

        Returns:
            (from_cache: bool, data: dict)
        """
        cached = await self.get(symbol, data_type, provider, **kwargs)

        if cached:
            return True, cached

        logger.info(f"Cache miss, fetching from {provider}...")
        data = await fetch_func(**kwargs)

        if data:
            await self.set(symbol, data_type, provider, data, ttl_seconds, **kwargs)

        return False, data if data else {}

    def _evict_oldest(self):
        """Evict oldest entry when cache is full."""
        if not self.cache:
            return

        oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k].created_at)

        del self.cache[oldest_key]
        self.stats["evictions"] += 1

        logger.debug(f"Evicted oldest: {oldest_key}")

    async def invalidate(
        self,
        symbol: Optional[str] = None,
        data_type: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> int:
        """
        Invalidate cache entries matching criteria.

        Args:
            symbol: Symbol to invalidate (None = all symbols)
            data_type: Data type to invalidate (None = all types)
            provider: Provider to invalidate (None = all providers)

        Returns:
            Number of entries invalidated
        """
        invalidated = 0
        keys_to_remove = []

        for key, entry in self.cache.items():
            if entry.is_expired():
                keys_to_remove.append(key)
                continue

            match = True

            if symbol:
                _, cached_symbol, _, _ = key.split(":", 3)
                match = match and cached_symbol.lower() == symbol.lower()

            if data_type:
                _, cached_type, _, _ = key.split(":", 3)
                match = match and cached_type == data_type

            if provider:
                _, _, cached_provider, _ = key.split(":", 3)
                match = match and cached_provider == provider

            if match:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.cache[key]
            invalidated += 1

        logger.info(f"Invalidated {invalidated} cache entries")
        return invalidated

    def get_source_weights(self) -> Dict[str, float]:
        """
        Calculate source reliability weights based on hit rate.

        Returns:
            Dict mapping provider → weight (0.0-1.0)
        """
        provider_hits: Dict[str, int] = {}
        provider_requests: Dict[str, int] = {}

        for entry in self.cache.values():
            if entry.hits == 0:
                provider_hits[entry.source] = provider_hits.get(entry.source, 0)
                provider_requests[entry.source] = provider_requests.get(entry.source, 0)
                continue

            provider_hits[entry.source] = (
                provider_hits.get(entry.source, 0) + entry.hits
            )
            provider_requests[entry.source] = (
                provider_requests.get(entry.source, 0) + entry.hits + 1
            )

        weights = {}

        for provider, hits in provider_hits.items():
            requests = provider_requests.get(provider, 1)

            if requests == 0:
                weights[provider] = 0.5
            else:
                weights[provider] = min(1.0, hits / requests)

        return weights

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        if self.stats["total_requests"] == 0:
            hit_rate = 0.0
        else:
            hit_rate = self.stats["cache_hits"] / self.stats["total_requests"]

        return {
            "enabled": self.enabled,
            "size": len(self.cache),
            "max_size": self.max_size,
            "total_requests": self.stats["total_requests"],
            "cache_hits": self.stats["cache_hits"],
            "cache_misses": self.stats["cache_misses"],
            "evictions": self.stats["evictions"],
            "hit_rate": hit_rate,
            "source_weights": self.get_source_weights(),
        }

    async def clear(self):
        """Clear all cache entries."""
        count = len(self.cache)
        self.cache.clear()
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "evictions": 0,
        }

        logger.info(f"Cleared {count} cache entries")


async def get_cache(config: Dict[str, Any] = None) -> MarketDataCache:
    """Get or create cache instance."""
    if config is None:
        from standalone.config import Config

        config = Config.load().__dict__

    return MarketDataCache(config)
