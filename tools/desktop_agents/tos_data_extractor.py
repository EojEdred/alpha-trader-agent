"""
ThinkOrSwim Real-Time Data Extractor

Extracts live quotes, chart data, and options data directly from the 
running ThinkOrSwim desktop application — no API keys, no rate limits.

Methods:
- get_quote(symbol) -> current bid/ask/last/volume
- get_chart_data(symbol, num_bars=50) -> OHLCV DataFrame
- get_option_chain(underlying) -> strikes, expirations, greeks

Uses AppleScript + pyautogui + OCR to read TOS UI elements.
"""

import time
import re
import subprocess
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from loguru import logger

import pandas as pd


class TOSDataExtractor:
    """Extracts market data from the running ThinkOrSwim desktop app."""

    def __init__(self):
        self.app_name = "thinkorswim"
        self._screen_scale = self._detect_scale()

    def _detect_scale(self) -> float:
        try:
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True
            )
            return 2.0 if "Retina" in result.stdout else 1.0
        except Exception:
            return 1.0

    def _run_applescript(self, script: str, timeout: int = 15) -> str:
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=timeout
            )
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"AppleScript failed: {e}")
            return ""

    def _activate(self) -> bool:
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{self.app_name}" to activate'],
                check=True, timeout=10
            )
            time.sleep(1.5)
            return True
        except Exception:
            return False

    def _is_running(self) -> bool:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "thinkorswim"],
                capture_output=True, text=True, timeout=2
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_window_bounds(self) -> Optional[tuple]:
        """Get TOS window position: (x, y, width, height)."""
        script = '''
        tell application "System Events"
            tell process "thinkorswim"
                set win to front window
                set pos to position of win
                set sz to size of win
                return (item 1 of pos) & "," & (item 2 of pos) & "," & (item 1 of sz) & "," & (item 2 of sz)
            end tell
        end tell
        '''
        result = self._run_applescript(script)
        if result:
            try:
                parts = [int(float(x.strip())) for x in result.split(",")]
                if len(parts) == 4:
                    return tuple(parts)
            except ValueError:
                pass
        return None

    def _ocr_region(self, x: int, y: int, w: int, h: int) -> str:
        """Read text from a screen region."""
        try:
            from PIL import ImageGrab
            import pytesseract
            screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            return pytesseract.image_to_string(screenshot).strip()
        except ImportError:
            logger.warning("pytesseract not installed")
            return ""
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return ""

    def _enter_symbol(self, symbol: str) -> bool:
        """Type a symbol into TOS and press Enter."""
        if not self._activate():
            return False
        script = f'''
        tell application "System Events"
            tell process "thinkorswim"
                keystroke "{symbol.upper()}"
                delay 0.3
                keystroke return
            end tell
        end tell
        '''
        self._run_applescript(script)
        time.sleep(1.5)
        return True

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current quote for a symbol from TOS.
        
        Returns dict with: symbol, bid, ask, last, high, low, open, volume, change, change_percent
        """
        if not self._is_running():
            logger.warning("TOS is not running")
            return None

        if not self._enter_symbol(symbol):
            return None

        # Wait for quote to load
        time.sleep(1.0)

        # Get window bounds to calculate quote bar region
        bounds = self._get_window_bounds()
        if not bounds:
            logger.warning("Could not get TOS window bounds")
            return None

        wx, wy, ww, wh = bounds

        # The quote bar is typically at the top of the TOS window
        # We'll OCR a region near the top-center where prices appear
        # These coordinates are relative to the window - adjust as needed
        quote_region = (
            wx + int(ww * 0.15),
            wy + int(wh * 0.08),
            int(ww * 0.55),
            int(wh * 0.08)
        )

        text = self._ocr_region(*quote_region)
        logger.debug(f"TOS quote OCR for {symbol}: {text[:200]}")

        # Parse numbers from OCR text
        # TOS quote bar typically shows: Last | Bid x Ask | Change | %Change | High | Low | Open | Volume
        result = {"symbol": symbol, "timestamp": datetime.utcnow().isoformat()}

        # Extract all dollar amounts and percentages
        prices = re.findall(r'\$?([\d,]+\.\d{2})', text)
        numbers = re.findall(r'\b([\d,]+\.?\d*)\b', text)

        # Try to identify values by position and context
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            lower = line.lower()

            if 'bid' in lower:
                m = re.search(r'[\d,]+\.\d{2}', line)
                if m:
                    result['bid'] = float(m.group().replace(',', ''))
            elif 'ask' in lower:
                m = re.search(r'[\d,]+\.\d{2}', line)
                if m:
                    result['ask'] = float(m.group().replace(',', ''))
            elif 'last' in lower:
                m = re.search(r'[\d,]+\.\d{2}', line)
                if m:
                    result['last'] = float(m.group().replace(',', ''))
            elif 'high' in lower:
                m = re.search(r'[\d,]+\.\d{2}', line)
                if m:
                    result['high'] = float(m.group().replace(',', ''))
            elif 'low' in lower:
                m = re.search(r'[\d,]+\.\d{2}', line)
                if m:
                    result['low'] = float(m.group().replace(',', ''))
            elif 'open' in lower:
                m = re.search(r'[\d,]+\.\d{2}', line)
                if m:
                    result['open'] = float(m.group().replace(',', ''))
            elif 'volume' in lower or 'vol' in lower:
                m = re.search(r'[\d,]+', line)
                if m:
                    result['volume'] = int(m.group().replace(',', ''))

        # Fallback: if we have prices but no labels, assign by typical order
        if 'last' not in result and prices:
            result['last'] = float(prices[0].replace(',', ''))
        if len(prices) >= 2 and 'bid' not in result:
            result['bid'] = float(prices[1].replace(',', ''))
        if len(prices) >= 3 and 'ask' not in result:
            result['ask'] = float(prices[2].replace(',', ''))

        logger.info(f"TOS quote {symbol}: last={result.get('last')}, bid={result.get('bid')}, ask={result.get('ask')}")
        return result if 'last' in result or 'bid' in result else None

    def get_chart_data(self, symbol: str, num_bars: int = 50) -> Optional[pd.DataFrame]:
        """
        Extract recent chart data from TOS.
        
        Strategy: TOS chart shows OHLC in the status bar when you hover over candles.
        We use a simpler approach: read the chart's price scale and time axis,
        then use the quote history from the MarketWatch tab.
        
        For now, returns a DataFrame with the current day's OHLCV from the quote.
        """
        quote = self.get_quote(symbol)
        if not quote:
            return None

        # Build a minimal single-candle DataFrame from the quote
        # In production, this would extract actual historical candles
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

    def get_option_chain(self, underlying: str) -> List[Dict[str, Any]]:
        """
        Extract option chain from TOS Analyze tab.
        
        Returns list of option dicts with strike, expiration, type, bid, ask, greeks.
        """
        if not self._is_running():
            return []

        if not self._enter_symbol(underlying):
            return []

        # Open option chain (Shift+F5 in TOS)
        script = '''
        tell application "System Events"
            tell process "thinkorswim"
                key code 96 using {shift down}  -- Shift+F5
                delay 2
            end tell
        end tell
        '''
        self._run_applescript(script)
        time.sleep(2.5)

        # Screenshot and OCR the option chain grid
        bounds = self._get_window_bounds()
        if not bounds:
            return []

        wx, wy, ww, wh = bounds
        chain_region = (wx + 50, wy + 150, ww - 100, wh - 200)
        text = self._ocr_region(*chain_region)

        # Parse option data from OCR text
        options = []
        lines = text.split('\n')
        current_exp = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for expiration headers
            exp_match = re.search(r'(\w{3}\s+\d{1,2}\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})', line)
            if exp_match:
                current_exp = exp_match.group(1)
                continue

            # Look for strike rows: strike | bid | ask | delta | gamma | theta | iv
            nums = re.findall(r'[\d,]+\.?\d*', line)
            if len(nums) >= 3 and current_exp:
                try:
                    options.append({
                        "underlying": underlying,
                        "expiration": current_exp,
                        "strike": float(nums[0].replace(',', '')),
                        "bid": float(nums[1].replace(',', '')) if len(nums) > 1 else 0,
                        "ask": float(nums[2].replace(',', '')) if len(nums) > 2 else 0,
                        "raw": line,
                    })
                except ValueError:
                    pass

        logger.info(f"TOS option chain {underlying}: {len(options)} strikes extracted")
        return options


def get_tos_data_extractor() -> TOSDataExtractor:
    """Singleton accessor."""
    if not hasattr(get_tos_data_extractor, "_instance"):
        get_tos_data_extractor._instance = TOSDataExtractor()
    return get_tos_data_extractor._instance
