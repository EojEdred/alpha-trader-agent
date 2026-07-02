"""
Strategy Data Feed

Fetches OHLCV data for strategy signal generation.
Supports multiple sources: Schwab (stocks), OANDA (forex), Polygon.io (futures), Yahoo Finance (fallback).

Usage:
    from strategies.data_feed import DataFeed

    feed = DataFeed()
    data = await feed.fetch_multi({"SPY": "schwab", "NQ1!": "polygon", "XAU_USD": "oanda"})
    # data["ohlcv"]["SPY"] -> pd.DataFrame with open, high, low, close, volume
"""

import asyncio
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from loguru import logger

import pandas as pd


# Symbol mapping for common aliases
SYMBOL_ALIASES = {
    "NQ1!": "NQ=F",
    "ES1!": "ES=F",
    "CL1!": "CL=F",
    "GC1!": "GC=F",
    "YM1!": "YM=F",
    "RTY1!": "RTY=F",
    "ZB1!": "ZB=F",
    "ZN1!": "ZN=F",
}

# Polygon.io futures mapping (Polygon uses standard CME symbols)
POLYGON_FUTURES = {
    "NQ1!": "NQZ25",  # Will need rollover logic in production
    "ES1!": "ESZ25",
    "CL1!": "CLZ25",
    "GC1!": "GCZ25",
    "YM1!": "YMZ25",
}

# Symbols that are futures contracts — routed to TradingView by default
FUTURES_SYMBOLS = {"NQ1!", "ES1!", "CL1!", "GC1!", "YM1!", "RTY1!", "ZB1!", "ZN1!"}


class DataFeed:
    """Fetches market data for strategy consumption."""

    def __init__(self):
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_ttl_seconds = 60
        self._polygon_key = os.getenv("POLYGON_API_KEY")

    def _resolve_source(self, symbol: str, requested_source: str) -> str:
        """Auto-route symbols to the best available data source."""
        # Futures symbols → TradingView (bypasses Yahoo 1m limits & Polygon paywall)
        if symbol in FUTURES_SYMBOLS and requested_source in ("schwab", "yahoo"):
            logger.info(f"Auto-routing futures symbol {symbol} from {requested_source} → tradingview")
            return "tradingview"
        return requested_source

    async def fetch(self, symbol: str, source: str = "schwab", period: str = "1d", interval: str = "5m") -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a single symbol.

        Args:
            symbol: Ticker symbol (can use aliases like NQ1!, ES1!)
            source: "schwab", "oanda", "polygon", "yahoo", "tradingview", "tos"
            period: How much history ("1d", "5d", "1mo")
            interval: Candle size ("1m", "5m", "15m", "1h", "1d")

        Returns:
            DataFrame with columns: open, high, low, close, volume, timestamp
        """
        # Auto-route to best source for symbol type
        source = self._resolve_source(symbol, source)

        # Resolve aliases
        if symbol in SYMBOL_ALIASES and source == "yahoo":
            symbol = SYMBOL_ALIASES[symbol]

        cache_key = f"{symbol}:{source}:{period}:{interval}"

        # Check cache
        if cache_key in self._cache:
            last = self._cache[cache_key].index[-1]
            last_dt = last.to_pydatetime()
            if last_dt.tzinfo is not None:
                last_dt = last_dt.replace(tzinfo=None)
            age = (datetime.utcnow() - last_dt).total_seconds()
            if age < self._cache_ttl_seconds:
                return self._cache[cache_key]

        try:
            if source == "schwab":
                df = await self._fetch_schwab(symbol, period, interval)
            elif source == "oanda":
                df = await self._fetch_oanda(symbol, period, interval)
            elif source == "polygon":
                df = await self._fetch_polygon(symbol, period, interval)
            elif source == "yahoo":
                df = await self._fetch_yahoo(symbol, period, interval)
            elif source == "tos":
                df = await self._fetch_tos(symbol)
            elif source == "tradingview":
                df = await self._fetch_tradingview(symbol, period, interval)
            else:
                logger.error(f"Unknown data source: {source}")
                return None

            if df is not None and not df.empty:
                self._cache[cache_key] = df
                return df

        except Exception as e:
            logger.error(f"Data feed error for {symbol}@{source}: {e}")

        return None

    async def fetch_multi(self, symbols: Dict[str, str], period: str = "1d", interval: str = "5m") -> Dict[str, Any]:
        """
        Fetch data for multiple symbols concurrently.

        Args:
            symbols: Dict of {symbol: source}

        Returns:
            Dict with key "ohlcv" containing {symbol: DataFrame}
        """
        tasks = []
        sym_list = []
        for sym, src in symbols.items():
            tasks.append(self.fetch(sym, src, period, interval))
            sym_list.append(sym)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        ohlcv = {}
        for sym, result in zip(sym_list, results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {sym}: {result}")
                continue
            if result is not None:
                ohlcv[sym] = result

        return {"ohlcv": ohlcv}

    async def _fetch_schwab(self, symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        """Fetch price history from Schwab API."""
        from tools.schwab import SchwabClient

        client = SchwabClient()
        if not client.client:
            logger.warning("Schwab client not available")
            return None

        try:
            freq_type, freq = self._schwab_interval_map(interval)
            period_type, periods = self._schwab_period_map(period)

            resp = client.client.get_price_history(
                symbol,
                period_type=period_type,
                period=periods,
                frequency_type=freq_type,
                frequency=freq,
            )

            if resp.status_code != 200:
                logger.warning(f"Schwab price history failed: HTTP {resp.status_code}")
                return None

            data = resp.json()
            candles = data.get("candles", [])

            if not candles:
                return None

            df = pd.DataFrame(candles)
            df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
            df = df.rename(columns={
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            })
            df = df.set_index("datetime")
            df = df.sort_index()

            return df[["open", "high", "low", "close", "volume"]]

        except Exception as e:
            logger.error(f"Schwab fetch error: {e}")
            return None

    async def _fetch_oanda(self, instrument: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        """Fetch candle data from OANDA API."""
        from tools.oanda import get_oanda_client

        client = get_oanda_client()
        if not client.client:
            logger.warning("OANDA client not available")
            return None

        try:
            granularity = self._oanda_interval_map(interval)
            count_map = {"1d": 288, "5d": 1440, "1mo": 8640}
            count = count_map.get(period, 288)

            import oandapyV20.endpoints.instruments as instruments

            params = {"count": count, "granularity": granularity, "price": "M"}
            r = instruments.InstrumentsCandles(instrument=instrument, params=params)
            resp = client.client.request(r)

            candles = resp.get("candles", [])
            if not candles:
                return None

            rows = []
            for c in candles:
                if c.get("complete"):
                    rows.append({
                        "timestamp": pd.to_datetime(c["time"]),
                        "open": float(c["mid"]["o"]),
                        "high": float(c["mid"]["h"]),
                        "low": float(c["mid"]["l"]),
                        "close": float(c["mid"]["c"]),
                        "volume": int(c["volume"]),
                    })

            df = pd.DataFrame(rows)
            df = df.set_index("timestamp")
            df = df.sort_index()
            return df

        except Exception as e:
            logger.error(f"OANDA fetch error: {e}")
            return None

    async def _fetch_polygon(self, symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        """Fetch futures data from Polygon.io."""
        if not self._polygon_key:
            logger.warning("Polygon.io API key not configured")
            return None

        try:
            import httpx

            # Map symbol to Polygon format
            poly_symbol = POLYGON_FUTURES.get(symbol, symbol)

            # Map interval to Polygon multiplier/timespan
            multiplier, timespan = self._polygon_interval_map(interval)

            # Calculate date range
            end_date = datetime.utcnow().strftime("%Y-%m-%d")
            days_back = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90}.get(period, 5)
            start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

            url = (
                f"https://api.polygon.io/v2/aggs/ticker/{poly_symbol}/range/"
                f"{multiplier}/{timespan}/{start_date}/{end_date}"
            )

            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params={"apiKey": self._polygon_key}, timeout=30)

            if resp.status_code != 200:
                logger.warning(f"Polygon.io failed: HTTP {resp.status_code} - {resp.text[:200]}")
                return None

            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None

            df = pd.DataFrame(results)
            df["t"] = pd.to_datetime(df["t"], unit="ms")
            df = df.rename(columns={
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "t": "timestamp",
            })
            df = df.set_index("timestamp")
            df = df.sort_index()
            return df[["open", "high", "low", "close", "volume"]]

        except Exception as e:
            logger.error(f"Polygon fetch error: {e}")
            return None

    async def _fetch_tos(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch quote data from ThinkOrSwim desktop app."""
        try:
            from tools.desktop_agents.tos_data_extractor import get_tos_data_extractor
            extractor = get_tos_data_extractor()
            quote = extractor.get_quote(symbol)
            if quote:
                row = {
                    "timestamp": pd.to_datetime(quote.get("timestamp", datetime.utcnow().isoformat())),
                    "open": quote.get("open", quote.get("last", 0)),
                    "high": quote.get("high", quote.get("last", 0)),
                    "low": quote.get("low", quote.get("last", 0)),
                    "close": quote.get("last", 0),
                    "volume": quote.get("volume", 0),
                }
                df = pd.DataFrame([row])
                df = df.set_index("timestamp")
                return df
            return None
        except Exception as e:
            logger.error(f"TOS fetch error: {e}")
            return None

    async def _fetch_tradingview(self, symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        """Fetch chart data from TradingView via browser extraction."""
        try:
            from tools.browser_agents.tradingview_data_extractor import get_tv_data_extractor
            extractor = await get_tv_data_extractor()
            
            # Map interval to TradingView format
            tv_interval = interval.replace("m", "") if interval.endswith("m") else interval
            if interval == "1h":
                tv_interval = "60"
            elif interval == "4h":
                tv_interval = "240"
            elif interval == "1d":
                tv_interval = "D"
            
            num_bars = {"1d": 100, "5d": 200, "1mo": 500}.get(period, 100)
            df = await extractor.get_chart_data(symbol, timeframe=tv_interval, num_bars=num_bars)
            return df
        except Exception as e:
            logger.error(f"TradingView fetch error: {e}")
            return None

    async def _fetch_yahoo(self, symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        """Fetch from Yahoo Finance as fallback."""
        try:
            import yfinance as yf

            # For futures, yfinance 1m often returns empty; upgrade to 5m
            if "=F" in symbol and interval == "1m":
                logger.info(f"Yahoo futures {symbol}: upgrading interval from 1m to 5m")
                interval = "5m"

            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                return None
            df = df.rename(columns=str.lower)
            return df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.error(f"Yahoo fetch error: {e}")
            return None

    def _schwab_interval_map(self, interval: str):
        """Map interval string to Schwab API params."""
        mapping = {
            "1m": ("minute", 1),
            "5m": ("minute", 5),
            "15m": ("minute", 15),
            "30m": ("minute", 30),
            "1h": ("daily", 1),  # Schwab doesn't do hourly, use daily
            "1d": ("daily", 1),
        }
        return mapping.get(interval, ("minute", 5))

    def _schwab_period_map(self, period: str):
        """Map period string to Schwab API params."""
        mapping = {
            "1d": ("day", 1),
            "5d": ("day", 5),
            "1mo": ("month", 1),
            "3mo": ("month", 3),
        }
        return mapping.get(period, ("day", 1))

    def _oanda_interval_map(self, interval: str) -> str:
        """Map interval to OANDA granularity."""
        mapping = {
            "1m": "M1",
            "5m": "M5",
            "15m": "M15",
            "1h": "H1",
            "4h": "H4",
            "1d": "D",
        }
        return mapping.get(interval, "M5")

    def _polygon_interval_map(self, interval: str):
        """Map interval to Polygon.io multiplier/timespan."""
        mapping = {
            "1m": (1, "minute"),
            "5m": (5, "minute"),
            "15m": (15, "minute"),
            "30m": (30, "minute"),
            "1h": (1, "hour"),
            "4h": (4, "hour"),
            "1d": (1, "day"),
        }
        return mapping.get(interval, (5, "minute"))
