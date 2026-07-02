"""
TradingView Chart Data Extractor

Extracts OHLCV data and prices directly from TradingView charts
using browser automation. No API keys needed.

Supports: stocks, futures, forex, crypto — any symbol TradingView charts.
"""

import asyncio
import re
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from loguru import logger

import pandas as pd


class TradingViewDataExtractor:
    """
    Extracts chart data from TradingView via browser automation.
    Uses direct Playwright for speed and reliability.
    """

    BASE_URL = "https://www.tradingview.com/chart"

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def _ensure_browser(self):
        """Lazy-init browser instance."""
        if self._page is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            self._page = await self._context.new_page()
            logger.info("TradingViewDataExtractor: browser launched")

    async def close(self):
        """Clean up browser resources."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        logger.info("TradingViewDataExtractor: browser closed")

    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current quote from TradingView chart page.
        
        Returns: dict with symbol, last, open, high, low, change, change_percent
        """
        await self._ensure_browser()
        page = self._page

        try:
            url = f"{self.BASE_URL}/?symbol={symbol}"
            logger.info(f"TradingView: loading quote for {symbol}")
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Extract from page title: "NQ1! 29,026.50 ▼ −4.79%"
            title = await page.title()
            logger.debug(f"TradingView page title: {title}")

            result = {"symbol": symbol, "timestamp": datetime.utcnow().isoformat()}

            # Parse price from title
            price_match = re.search(r'([\d,]+\.\d{2})', title)
            if price_match:
                result["last"] = float(price_match.group(1).replace(',', ''))

            # Parse O/H/L/C from the top bar text
            # The top bar shows: "O29,016.25 H29,042.25 L28,781.25 C28,829.25 -186.50 (-0.64%)"
            # Try multiple selectors where this might appear
            ohlc_text = None
            
            # Method 1: Look for the header/title area that contains O/H/L/C
            header_selectors = [
                '[data-name="legend-series-item"]',
                'div[class*="title"]',
                'div[class*="header"]',
                'div[class*="quote"]',
                '.chart-gui-wrapper div',
            ]
            
            for selector in header_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for el in elements:
                        text = await el.inner_text()
                        if 'O' in text and 'H' in text and 'L' in text and 'C' in text:
                            ohlc_text = text
                            break
                    if ohlc_text:
                        break
                except Exception:
                    continue

            # Method 2: Search all text on page for O/H/L/C pattern
            if not ohlc_text:
                try:
                    body_text = await page.inner_text('body')
                    # Find pattern like O29,016.25 H29,042.25 L28,781.25 C28,829.25
                    match = re.search(r'O([\d,]+\.\d{2})\s+H([\d,]+\.\d{2})\s+L([\d,]+\.\d{2})\s+C([\d,]+\.\d{2})', body_text)
                    if match:
                        result["open"] = float(match.group(1).replace(',', ''))
                        result["high"] = float(match.group(2).replace(',', ''))
                        result["low"] = float(match.group(3).replace(',', ''))
                        result["close"] = float(match.group(4).replace(',', ''))
                        logger.info(f"TradingView OHLC for {symbol}: O={result['open']} H={result['high']} L={result['low']} C={result['close']}")
                except Exception as e:
                    logger.debug(f"Body text OHLC parse failed: {e}")

            # Parse from ohlc_text if found
            if ohlc_text:
                o_match = re.search(r'O([\d,]+\.\d{2})', ohlc_text)
                h_match = re.search(r'H([\d,]+\.\d{2})', ohlc_text)
                l_match = re.search(r'L([\d,]+\.\d{2})', ohlc_text)
                c_match = re.search(r'C([\d,]+\.\d{2})', ohlc_text)
                
                if o_match: result["open"] = float(o_match.group(1).replace(',', ''))
                if h_match: result["high"] = float(h_match.group(1).replace(',', ''))
                if l_match: result["low"] = float(l_match.group(1).replace(',', ''))
                if c_match: result["close"] = float(c_match.group(1).replace(',', ''))

            # Use close/last as fallback for missing values
            if "close" not in result and "last" in result:
                result["close"] = result["last"]
            if "last" not in result and "close" in result:
                result["last"] = result["close"]

            # Parse change from title
            change_match = re.search(r'([+-]?[\d,]+\.\d{2})\s*\(([+-]?[\d.]+)%\)', title)
            if change_match:
                result["change"] = float(change_match.group(1).replace(',', ''))
                result["change_percent"] = float(change_match.group(2))

            if "last" in result or "close" in result:
                logger.info(f"TradingView quote {symbol}: last={result.get('last')}, close={result.get('close')}")
                return result
            
            return None

        except Exception as e:
            logger.error(f"TradingView quote failed for {symbol}: {e}")
            return None

    async def get_chart_data(
        self,
        symbol: str,
        timeframe: str = "60",
        num_bars: int = 100,
    ) -> Optional[pd.DataFrame]:
        """
        Extract OHLCV data from a TradingView chart.
        
        Uses a hybrid approach:
        1. Gets current quote from TradingView (real-time, accurate)
        2. Fills historical data from Yahoo Finance
        
        Args:
            symbol: TradingView symbol (e.g., "NQ1!", "ES1!", "XAUUSD", "AAPL")
            timeframe: Chart interval in minutes ("1", "5", "15", "60", "240", "D")
            num_bars: Number of candles to extract
            
        Returns:
            DataFrame with columns: open, high, low, close, volume
        """
        # Step 1: Get current quote from TradingView
        quote = await self.get_quote(symbol)
        
        # Step 2: Get historical data from Yahoo Finance
        yahoo_sym = self._tv_to_yahoo(symbol)
        hist_df = await self._fetch_yahoo_history(yahoo_sym, num_bars, timeframe)
        
        if hist_df is not None and not hist_df.empty:
            # Step 3: Update the last candle with TradingView's real-time data
            if quote and "close" in quote:
                # Update the most recent candle's close
                hist_df.iloc[-1, hist_df.columns.get_loc("close")] = quote["close"]
                if "high" in quote:
                    hist_df.iloc[-1, hist_df.columns.get_loc("high")] = max(
                        hist_df.iloc[-1]["high"], quote["high"]
                    )
                if "low" in quote:
                    hist_df.iloc[-1, hist_df.columns.get_loc("low")] = min(
                        hist_df.iloc[-1]["low"], quote["low"]
                    )
                logger.info(f"TradingView: updated last candle for {symbol} with real-time close={quote['close']}")
            return hist_df
        
        # Fallback: return single-candle DataFrame from quote
        if quote and "close" in quote:
            return self._make_single_candle(symbol, quote["close"])
        
        return None

    def _tv_to_yahoo(self, symbol: str) -> str:
        """Convert TradingView symbol to Yahoo Finance symbol."""
        mapping = {
            "NQ1!": "NQ=F",
            "ES1!": "ES=F",
            "CL1!": "CL=F",
            "GC1!": "GC=F",
            "YM1!": "YM=F",
            "RTY1!": "RTY=F",
            "ZB1!": "ZB=F",
            "ZN1!": "ZN=F",
            "XAUUSD": "GC=F",
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "JPY=X",
        }
        return mapping.get(symbol.upper(), symbol)

    async def _fetch_yahoo_history(self, symbol: str, num_bars: int, timeframe: str) -> Optional[pd.DataFrame]:
        """Fetch historical data from Yahoo Finance."""
        try:
            import yfinance as yf
            
            # Determine period and interval
            period = "5d" if num_bars <= 100 else "1mo"
            
            # Convert timeframe to Yahoo interval
            interval_map = {
                "1": "1m", "5": "5m", "15": "15m", "30": "30m",
                "60": "1h", "240": "1h", "D": "1d",
            }
            interval = interval_map.get(timeframe, "1h")
            
            # Yahoo futures: 1m often empty, upgrade to 5m
            if "=F" in symbol and interval == "1m":
                interval = "5m"
            
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                return None
            
            df = df.rename(columns=str.lower)
            df = df[["open", "high", "low", "close", "volume"]]
            
            if len(df) > num_bars:
                df = df.iloc[-num_bars:]
            
            return df
        except Exception as e:
            logger.warning(f"Yahoo fallback failed for {symbol}: {e}")
            return None

    def _make_single_candle(self, symbol: str, price: float) -> pd.DataFrame:
        """Create a minimal single-candle DataFrame."""
        now = datetime.utcnow()
        df = pd.DataFrame([{
            "timestamp": now,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0,
        }])
        df = df.set_index("timestamp")
        return df

    async def get_indicators(self, symbol: str, timeframe: str = "5") -> Dict[str, Any]:
        """
        Read visible indicator values from a TradingView chart.
        
        Returns dict with RSI, MACD, SMA, EMA, VWAP if visible.
        """
        await self._ensure_browser()
        page = self._page

        try:
            url = f"{self.BASE_URL}/?symbol={symbol}&interval={timeframe}"
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            result = {}
            
            # Read current price first
            quote = await self.get_quote(symbol)
            if quote:
                result.update(quote)
            
            # Look for indicator pane values in the DOM
            # TradingView shows indicators in separate panes below the chart
            indicator_patterns = [
                ("rsi", r'RSI\D*(\d+\.?\d*)'),
                ("macd_line", r'MACD\D*(\d+\.?\d*)'),
                ("macd_signal", r'Signal\D*(\d+\.?\d*)'),
                ("sma_20", r'SMA\s*20\D*(\d+\.?\d*)'),
                ("sma_50", r'SMA\s*50\D*(\d+\.?\d*)'),
                ("ema_9", r'EMA\s*9\D*(\d+\.?\d*)'),
                ("vwap", r'VWAP\D*(\d+\.?\d*)'),
            ]
            
            body_text = await page.inner_text('body')
            for key, pattern in indicator_patterns:
                match = re.search(pattern, body_text, re.I)
                if match:
                    try:
                        result[key] = float(match.group(1))
                    except ValueError:
                        pass
            
            return result

        except Exception as e:
            logger.error(f"TradingView indicators failed for {symbol}: {e}")
            return {}


# Singleton
_tv_extractor: Optional[TradingViewDataExtractor] = None

async def get_tv_data_extractor() -> TradingViewDataExtractor:
    global _tv_extractor
    if _tv_extractor is None:
        _tv_extractor = TradingViewDataExtractor()
    return _tv_extractor
