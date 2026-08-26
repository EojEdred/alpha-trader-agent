"""
Massive API Market Data Provider

Formerly Polygon.io, Massive provides institutional-grade US market data:
- Stock/ETF aggregates (OHLCV)
- Real-time and delayed quotes/trades
- Options snapshots and aggregates
- Futures/forex/crypto data
- Fundamentals, news, and alternative signals

Configured via config.yaml under market_data_apis.massive.

Usage:
    from market_data.providers.massive_provider import MassiveProvider

    provider = MassiveProvider(config)
    ohlcv = await provider.get_aggregates("AAPL", multiplier=1, timespan="day", days=30)
    snapshot = await provider.get_snapshot("AAPL")
"""

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger


DEFAULT_BASE_URL = "https://api.massive.com"


class MassiveError(Exception):
    """Raised when a Massive API call fails."""

    def __init__(self, message: str, endpoint: Optional[str] = None, status: Optional[int] = None):
        super().__init__(message)
        self.endpoint = endpoint
        self.status = status


class MassiveProvider:
    """
    Async provider for the Massive REST API.

    Falls back to disabled mode when no API key is present, returning None
    from data methods so the MarketDataFetcher can try the next provider.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        api_config = self.config.get("market_data_apis", {}).get("massive", {})
        self.api_key = api_config.get("api_key") or os.environ.get("MASSIVE_API_KEY")
        self.base_url = api_config.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self.enabled = bool(api_config.get("enabled", False)) and bool(self.api_key)
        self.timeout = float(api_config.get("timeout_seconds", 30.0))
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            params = {}
            if self.api_key:
                params["apiKey"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                params=params,
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    # ------------------------------------------------------------------
    # REST helpers
    # ------------------------------------------------------------------

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Make an authenticated GET request and return JSON, or None on failure."""
        if not self.enabled:
            logger.debug(f"Massive API disabled; skipping {endpoint}")
            return None

        try:
            response = await self._get_client().get(endpoint, params=params)
            if response.status_code == 429:
                logger.warning(f"Massive API rate limit hit on {endpoint}")
                raise MassiveError("Rate limited", endpoint=endpoint, status=429)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"Massive API {endpoint} returned {e.response.status_code}")
            raise MassiveError(
                f"HTTP {e.response.status_code}",
                endpoint=endpoint,
                status=e.response.status_code,
            )
        except Exception as e:
            logger.warning(f"Massive API {endpoint} request failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Aggregates / OHLCV
    # ------------------------------------------------------------------

    async def get_aggregates(
        self,
        ticker: str,
        multiplier: int = 1,
        timespan: str = "day",
        days: int = 30,
        adjusted: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch OHLCV aggregates for a ticker.

        Args:
            ticker: Symbol (e.g. AAPL, SPY).
            multiplier: Aggregate multiplier.
            timespan: minute, hour, day, week, month, quarter, year.
            days: Number of calendar days to look back.
            adjusted: Adjust for splits/dividends.
        """
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        from_str = start.strftime("%Y-%m-%d")
        to_str = end.strftime("%Y-%m-%d")

        endpoint = f"/v2/aggs/ticker/{ticker.upper()}/range/{multiplier}/{timespan}/{from_str}/{to_str}"
        params = {"adjusted": "true" if adjusted else "false", "sort": "asc", "limit": 50000}
        return await self._get(endpoint, params=params)

    async def get_ohlcv(
        self,
        ticker: str,
        multiplier: int = 1,
        timespan: str = "day",
        days: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch normalized OHLCV data compatible with Alpha Trader's MarketDataFetcher.

        Returns:
            {
                "symbol": ticker,
                "timeframe": f"{multiplier}{timespan}",
                "candles": [
                    {"timestamp": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...},
                    ...
                ]
            }
        """
        data = await self.get_aggregates(ticker, multiplier, timespan, days)
        if data is None:
            return None

        results = data.get("results", [])
        candles = []
        for bar in results:
            # Massive aggregates: t, o, h, l, c, v, vw, n
            ts_ms = bar.get("t")
            ts = datetime.fromtimestamp(ts_ms / 1000.0).isoformat() if ts_ms else None
            candles.append(
                {
                    "timestamp": ts,
                    "open": bar.get("o"),
                    "high": bar.get("h"),
                    "low": bar.get("l"),
                    "close": bar.get("c"),
                    "volume": bar.get("v"),
                    "vwap": bar.get("vw"),
                    "trades": bar.get("n"),
                }
            )

        return {
            "symbol": ticker.upper(),
            "timeframe": f"{multiplier}{timespan}",
            "source": "massive",
            "candles": candles,
        }

    # ------------------------------------------------------------------
    # Snapshots and quotes
    # ------------------------------------------------------------------

    async def get_snapshot(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch a single-ticker snapshot (quote, last trade, daily stats)."""
        return await self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker.upper()}")

    async def get_last_trade(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch the last trade for a stock ticker."""
        return await self._get(f"/v2/last/trade/{ticker.upper()}")

    async def get_daily_open_close(self, ticker: str, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch daily open/close for a date (defaults to yesterday)."""
        if date is None:
            date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        return await self._get(f"/v1/open-close/{ticker.upper()}/{date}")

    async def get_previous_close(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch previous closing prices."""
        return await self._get(f"/v2/aggs/ticker/{ticker.upper()}/prev")

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    async def get_options_snapshot(
        self,
        underlying: str,
        option_ticker: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch an option contract snapshot."""
        return await self._get(
            f"/v3/snapshot/options/{underlying.upper()}/{option_ticker.upper()}"
        )

    async def get_options_chain(
        self,
        underlying: str,
        expiration_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch all options snapshots for an underlying asset."""
        params = {}
        if expiration_date:
            params["expiration_date"] = expiration_date
        return await self._get(
            f"/v3/snapshot/options/{underlying.upper()}", params=params
        )

    # ------------------------------------------------------------------
    # Reference data
    # ------------------------------------------------------------------

    async def search_tickers(
        self,
        query: str,
        limit: int = 20,
        market: str = "stocks",
    ) -> Optional[Dict[str, Any]]:
        """Search tickers by symbol/name."""
        return await self._get(
            "/v3/reference/tickers",
            params={"search": query, "limit": limit, "market": market, "active": "true"},
        )

    async def get_ticker_details(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch reference details for a ticker."""
        return await self._get(f"/v3/reference/tickers/{ticker.upper()}")

    # ------------------------------------------------------------------
    # News and fundamentals
    # ------------------------------------------------------------------

    async def get_news(
        self,
        ticker: Optional[str] = None,
        limit: int = 20,
    ) -> Optional[Dict[str, Any]]:
        """Fetch news articles, optionally filtered by ticker."""
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker.upper()
        return await self._get("/v2/reference/news", params=params)

    async def get_fundamentals(
        self,
        ticker: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch stock financials (income, balance, cash flow)."""
        return await self._get(f"/vX/reference/financials/{ticker.upper()}")
