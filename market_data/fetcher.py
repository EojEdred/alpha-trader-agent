"""
Market Data Fetcher

Automatic data fetching from multiple sources without requiring manual URLs.

Sources:
- OANDA API (already integrated)
- Alpha Vantage (fundamentals)
- Polygon (options flow)
- NewsAPI (news)
"""

import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from loguru import logger
import aiohttp

from market_data.cache import get_cache


class MarketDataFetcher:
    """Fetches market data from multiple API sources."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.apis = self.config.get("market_data_apis", {})
        self.session = aiohttp.ClientSession()
        self.cache = asyncio.run(get_cache(config))

    async def fetch_symbol_data(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch comprehensive data for a symbol from multiple sources.

        Returns:
            {
                'symbol': str,
                'technical': OHLCV data,
                'fundamentals': Earnings, estimates, ratios,
                'news': List[news items],
                'options_flow': IV, volume, positioning,
                'fetched_at': datetime
            }

        All sources run in parallel. Failed sources are None.
        Uses cache and ML source weighting.
        """
        logger.info(f"Fetching market data for {symbol}...")

        tasks = [
            self._fetch_technical_cached(symbol),
            self._fetch_fundamentals_cached(symbol),
            self._fetch_news_cached(symbol),
            self._fetch_options_flow_cached(symbol),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        cache_stats = self.cache.get_stats()

        data = {
            "symbol": symbol,
            "technical": results[0] if not isinstance(results[0], Exception) else None,
            "fundamentals": results[1]
            if not isinstance(results[1], Exception) else None,
            "news": results[2] if not isinstance(results[2], Exception) else None,
            "options_flow": results[3] if not isinstance(results[3], Exception) else None,
            "fetched_at": datetime.utcnow(),
            "cache_stats": cache_stats,
            "source_weights": cache_stats.get("source_weights", {})
        }

        return data

    async def _fetch_technical_cached(self, symbol: str) -> Optional[Dict[str, Any]]:
        from_cache, fetch_func = self._fetch_technical
        return await self.cache.get_or_fetch(symbol, "technical", "oanda", fetch_func)

    async def _fetch_fundamentals_cached(self, symbol: str) -> Optional[Dict[str, Any]]:
        from_cache, fetch_func = self._fetch_fundamentals
        return await self.cache.get_or_fetch(symbol, "fundamentals", "alphavantage", fetch_func)

    async def _fetch_news_cached(self, symbol: str) -> Optional[List[Dict[str, Any]]]:
        from_cache, fetch_func = self._fetch_news
        result = await self.cache.get_or_fetch(symbol, "news", "newsapi.org", fetch_func)
        return result.get("data") if result else []

    async def _fetch_options_flow_cached(self, symbol: str) -> Optional[Dict[str, Any]]:
        from_cache, fetch_func = self._fetch_options_flow
        return await self.cache.get_or_fetch(symbol, "options_flow", "polygon", fetch_func)

        All sources run in parallel. Failed sources are None.
        """
        logger.info(f"Fetching market data for {symbol}...")

        tasks = [
            self._fetch_technical(symbol),
            self._fetch_fundamentals(symbol),
            self._fetch_news(symbol),
            self._fetch_options_flow(symbol),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            "symbol": symbol,
            "technical": results[0] if not isinstance(results[0], Exception) else None,
            "fundamentals": results[1]
            if not isinstance(results[1], Exception)
            else None,
            "news": results[2] if not isinstance(results[2], Exception) else None,
            "options_flow": results[3]
            if not isinstance(results[3], Exception)
            else None,
            "fetched_at": datetime.utcnow(),
        }

    async def _fetch_technical(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch OHLCV data from OANDA or configured provider."""
        if not self.apis.get("technical", {}).get("enabled", True):
            logger.info(f"Technical data disabled for {symbol}")
            return None

        try:
            provider = self.apis["technical"].get("provider", "oanda")

            if provider == "oanda":
                return await self._fetch_oanda_technical(symbol)
            else:
                return await self._fetch_alphavantage_technical(symbol)

        except Exception as e:
            logger.error(f"Failed to fetch technical data for {symbol}: {e}")
            return None

    async def _fetch_oanda_technical(self, symbol: str) -> Dict[str, Any]:
        """Fetch OHLCV data from OANDA API."""
        try:
            from tools.oanda import get_oanda_client

            oanda = get_oanda_client()
            instrument = self._convert_symbol_to_oanda(symbol)

            candles = await oanda.get_candles(
                instrument=instrument,
                granularity="H1",
                count=24,  # Last 24 hours
            )

            if not candles or len(candles) == 0:
                logger.warning(f"No candle data for {instrument}")
                return {}

            latest = candles[-1]

            return {
                "provider": "oanda",
                "instrument": instrument,
                "open": latest["mid"]["o"],
                "high": latest["mid"]["h"],
                "low": latest["mid"]["l"],
                "close": latest["mid"]["c"],
                "volume": latest["volume"],
                "timestamp": datetime.fromisoformat(
                    latest["time"].replace("Z", "+00:00")
                ),
                "ma_short": self._calculate_ma(candles, 5),
                "ma_long": self._calculate_ma(candles, 20),
                "rsi": self._calculate_rsi(candles),
            }

        except Exception as e:
            logger.error(f"OANDA technical fetch error for {symbol}: {e}")
            raise

    async def _fetch_alphavantage_technical(self, symbol: str) -> Dict[str, Any]:
        """Fetch OHLCV from Alpha Vantage."""
        api_key = self.apis["technical"].get("api_key")

        if not api_key:
            logger.warning("Alpha Vantage API key not configured")
            return {}

        try:
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "TIME_SERIES_INTRADAY",
                "symbol": symbol,
                "interval": "60min",
                "outputsize": "full",
                "apikey": api_key,
            }

            async with self.session.get(url, params=params) as response:
                data = await response.json()

                if "Time Series (60min)" not in data:
                    logger.warning(f"Alpha Vantage response: {data}")
                    return {}

                time_series = data["Time Series (60min)"]
                latest_key = list(time_series.keys())[-1]
                latest = time_series[latest_key]

                candles = list(time_series.values())[-24:]

                ma_short = sum(c["4. close"] for c in candles[-5:]) / 5
                ma_long = sum(c["4. close"] for c in candles[-20:]) / 20

                return {
                    "provider": "alphavantage",
                    "symbol": symbol,
                    "open": latest["1. open"],
                    "high": latest["2. high"],
                    "low": latest["3. low"],
                    "close": latest["4. close"],
                    "volume": latest.get("5. volume", 0),
                    "timestamp": datetime.strptime(latest_key, "%Y-%m-%d %H:%M:%S"),
                    "ma_short": ma_short,
                    "ma_long": ma_long,
                }

        except Exception as e:
            logger.error(f"Alpha Vantage technical fetch error for {symbol}: {e}")
            return {}

    async def _fetch_fundamentals(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch fundamentals from Alpha Vantage."""
        if not self.apis.get("fundamentals", {}).get("enabled", True):
            logger.info(f"Fundamentals data disabled for {symbol}")
            return None

        api_key = self.apis["fundamentals"].get("api_key")

        if not api_key:
            logger.warning("Alpha Vantage fundamentals API key not configured")
            return {}

        try:
            url = "https://www.alphavantage.co/query"

            tasks = [
                self._fetch_overview(symbol, url, api_key),
                self._fetch_earnings(symbol, url, api_key),
                self._fetch_income_statement(symbol, url, api_key),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            return {
                "provider": "alphavantage",
                "symbol": symbol,
                "overview": results[0]
                if not isinstance(results[0], Exception)
                else None,
                "earnings": results[1]
                if not isinstance(results[1], Exception)
                else None,
                "income": results[2] if not isinstance(results[2], Exception) else None,
            }

        except Exception as e:
            logger.error(f"Fundamentals fetch error for {symbol}: {e}")
            return None

    async def _fetch_overview(
        self, symbol: str, url: str, api_key: str
    ) -> Dict[str, Any]:
        """Fetch company overview from Alpha Vantage."""
        params = {"function": "OVERVIEW", "symbol": symbol, "apikey": api_key}

        async with self.session.get(url, params=params) as response:
            data = await response.json()

            if "Global Quote" not in data:
                return {}

            return data["Global Quote"]

    async def _fetch_earnings(
        self, symbol: str, url: str, api_key: str
    ) -> Dict[str, Any]:
        """Fetch earnings data from Alpha Vantage."""
        params = {"function": "EARNINGS", "symbol": symbol, "apikey": api_key}

        async with self.session.get(url, params=params) as response:
            data = await response.json()

            if "quarterlyEarnings" not in data:
                return {}

            return data["quarterlyEarnings"]

    async def _fetch_income_statement(
        self, symbol: str, url: str, api_key: str
    ) -> Dict[str, Any]:
        """Fetch income statement from Alpha Vantage."""
        params = {"function": "INCOME_STATEMENT", "symbol": symbol, "apikey": api_key}

        async with self.session.get(url, params=params) as response:
            data = await response.json()

            if "annualReports" not in data:
                return {}

            return data["annualReports"]

    async def _fetch_news(self, symbol: str) -> Optional[List[Dict[str, Any]]]:
        """Fetch recent news with sentiment analysis."""
        if not self.apis.get("news", {}).get("enabled", True):
            logger.info(f"News data disabled for {symbol}")
            return None

        provider = self.apis["news"].get("provider", "newsapi")
        api_key = self.apis["news"].get("api_key")

        if not api_key:
            logger.warning("News API key not configured")
            return []

        try:
            if provider == "newsapi":
                return await self._fetch_newsapi(symbol, api_key)
            else:
                return await self._fetch_alphavantage_news(symbol, api_key)

        except Exception as e:
            logger.error(f"News fetch error for {symbol}: {e}")
            return []

    async def _fetch_newsapi(self, symbol: str, api_key: str) -> List[Dict[str, Any]]:
        """Fetch news from NewsAPI.org."""
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": f'"{symbol}" OR "{symbol} stock"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": api_key,
        }

        async with self.session.get(url, params=params) as response:
            data = await response.json()

            if data.get("status") != "ok":
                logger.warning(f"NewsAPI error: {data}")
                return []

            articles = []
            for article in data.get("articles", [])[:10]:
                articles.append(
                    {
                        "title": article.get("title"),
                        "description": article.get("description"),
                        "url": article.get("url"),
                        "publishedAt": article.get("publishedAt"),
                        "source": article.get("source", {}).get("name"),
                        "sentiment": "neutral",
                    }
                )

            return articles

    async def _fetch_alphavantage_news(
        self, symbol: str, api_key: str
    ) -> List[Dict[str, Any]]:
        """Fetch news from Alpha Vantage."""
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": symbol,
            "apikey": api_key,
            "limit": 10,
        }

        async with self.session.get(url, params=params) as response:
            data = await response.json()

            if "feed" not in data:
                logger.warning(f"Alpha Vantage news error: {data}")
                return []

            articles = []
            for item in data["feed"][:10]:
                articles.append(
                    {
                        "title": item.get("title"),
                        "description": item.get("summary"),
                        "url": item.get("url"),
                        "publishedAt": item.get("time_published"),
                        "source": "alphavantage",
                        "sentiment": item.get("overall_sentiment_score", "neutral"),
                    }
                )

            return articles

    async def _fetch_options_flow(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch options flow, IV, and positioning."""
        if not self.apis.get("options_flow", {}).get("enabled", False):
            logger.info(f"Options data disabled for {symbol}")
            return None

        provider = self.apis["options_flow"].get("provider")

        if provider == "polygon":
            return await self._fetch_polygon_options(symbol)
        elif provider == "thinkorswim":
            return await self._fetch_thinkorswim_options(symbol)
        else:
            logger.warning(f"Options provider not configured: {provider}")
            return None

    async def _fetch_polygon_options(self, symbol: str) -> Dict[str, Any]:
        """Fetch options flow from Polygon.io."""
        api_key = self.apis["options_flow"].get("api_key")

        if not api_key:
            logger.warning("Polygon API key not configured")
            return {}

        try:
            url = f"https://api.polygon.io/v3/aggs/ticker/{symbol}/range/1/day/adjusted"
            headers = {"Authorization": f"Bearer {api_key}"}
            params = {
                "from": (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "to": datetime.utcnow().strftime("%Y-%m-%d"),
            }

            async with self.session.get(
                url, headers=headers, params=params
            ) as response:
                data = await response.json()

                if "results" not in data or len(data["results"]) == 0:
                    logger.warning(f"Polygon options data empty for {symbol}")
                    return {}

                return {
                    "provider": "polygon",
                    "symbol": symbol,
                    "aggs": data["results"],
                }

        except Exception as e:
            logger.error(f"Polygon options fetch error for {symbol}: {e}")
            return {}

    async def _fetch_thinkorswim_options(self, symbol: str) -> Dict[str, Any]:
        """Fetch options flow from Thinkorswim."""
        logger.warning("Thinkorswim options not yet implemented")
        return {}

    def _convert_symbol_to_oanda(self, symbol: str) -> str:
        """Convert symbol to OANDA instrument format."""
        symbol_map = {
            "SPY": "US500USD",
            "QQQ": "US100USD",
            "GLD": "XAUUSD",
            "SLV": "XAGUSD",
            "XAUUSD": "XAUUSD",
            "NQ": "US100USD",
            "ES": "US500USD",
            "GC": "XAUUSD",
            "SI": "XAGUSD",
        }

        return symbol_map.get(symbol, symbol)

    def _calculate_ma(self, candles: List[Dict[str, Any]], period: int) -> float:
        """Calculate simple moving average."""
        if len(candles) < period:
            return 0.0

        closes = [c["mid"]["c"] for c in candles[-period:]]
        return sum(closes) / len(closes)

    def _calculate_rsi(self, candles: List[Dict[str, Any]], period: int = 14) -> float:
        """Calculate RSI indicator."""
        if len(candles) < period + 1:
            return 50.0

        closes = [c["mid"]["c"] for c in candles]

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]

            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))

        if not gains or not losses:
            return 50.0

        avg_gain = sum(gains) / len(gains)
        avg_loss = sum(losses) / len(losses)

        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rs_list = [rs]

        for change in gains + losses:
            if change > 0:
                rs_list.append((rs * (period - 1) + change) / (period + 1))
            else:
                rs_list.append((rs * (period - 1)) / abs(change))

        rs = rs_list[-1] if rs_list else rs

        rsi = 100 - (100 / (1 + rs))

        return rsi

    async def close(self):
        """Close the aiohttp session."""
        await self.session.close()


async def fetch_market_data_for_symbols(
    symbols: List[str], config: Dict[str, Any] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch market data for multiple symbols.

    Returns:
        {
            'symbol': {technical, fundamentals, news, options_flow, fetched_at}
        }
    """
    fetcher = MarketDataFetcher(config)

    tasks = {symbol: fetcher.fetch_symbol_data(symbol) for symbol in symbols}

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    output = {}
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to fetch {symbol}: {result}")
            output[symbol] = {}
        else:
            output[symbol] = result

    await fetcher.close()

    return output
