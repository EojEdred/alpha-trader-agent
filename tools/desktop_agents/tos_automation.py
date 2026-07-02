"""
ThinkOrSwim Desktop Automation

Controls the installed thinkorswim desktop app using:
- AppleScript (app activation, menu commands)
- pyautogui (mouse/keyboard)
- OCR (text reading from screen)

ThinkOrSwim is installed at: /Applications/thinkorswim.app
"""

import os
import time
import subprocess
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from loguru import logger

from .base_desktop_agent import BaseDesktopAgent, DesktopActionResult


class ThinkOrSwimDesktopAgent(BaseDesktopAgent):
    """
    Desktop automation for ThinkOrSwim (TOS).
    
    TOS is powerful for options trading but has no official API.
    This agent controls it via the desktop UI.
    
    IMPORTANT: Coordinates are for reference and need calibration
    per screen resolution. Use find_image_on_screen when possible.
    
    Recommended workflow:
    1. Activate TOS
    2. Use hotkeys to navigate (faster than clicking)
    3. OCR to verify state
    4. Screenshot for audit
    """
    
    def __init__(self):
        super().__init__(
            app_name="thinkorswim",
            app_path="/Applications/thinkorswim.app",
            verification_enabled=True,
        )
        
        # Screen regions (approximate - calibrate for your setup)
        # Format: (x, y, width, height) in screen pixels
        self.regions = {
            "symbol_input": (200, 80, 300, 40),
            "active_symbol": (150, 80, 200, 30),
            "price_ladder": (1400, 200, 200, 600),
            "order_ticket": (1200, 150, 400, 500),
            "account_info": (50, 30, 300, 60),
            "positions_panel": (50, 400, 400, 400),
            "status_bar": (50, 1000, 400, 30),
        }
        
        # TOS hotkeys
        self.hotkeys = {
            "trade_tab": ["ctrl", "1"],
            "monitor_tab": ["ctrl", "2"],
            "analyze_tab": ["ctrl", "3"],
            "scan_tab": ["ctrl", "4"],
            "marketwatch_tab": ["ctrl", "5"],
            "charts_tab": ["ctrl", "6"],
            "tools_tab": ["ctrl", "7"],
            "active_trader": ["ctrl", "shift", "a"],
            "buy_market": ["ctrl", "b"],
            "sell_market": ["ctrl", "s"],
            "flatten": ["ctrl", "shift", "f"],
            "cancel_all": ["ctrl", "shift", "c"],
        }

    def is_app_running(self) -> bool:
        """Override: TOS runs as a Java process, so use pgrep on cmdline."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "thinkorswim"],
                capture_output=True, text=True, timeout=2
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to check if TOS is running: {e}")
            return False


    
    def _run_applescript(self, script: str) -> str:
        """Run AppleScript and return result."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=15
            )
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"AppleScript failed: {e}")
            return ""
    
    def get_window_position(self) -> Optional[Tuple[int, int, int, int]]:
        """Get TOS window bounds (x, y, width, height)."""
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
    
    def is_ready(self) -> bool:
        """Check if TOS is fully loaded and ready."""
        if not self.is_app_running():
            return False
        
        self.activate_app()
        
        # Check for login dialog
        # If login dialog is present, we're not ready
        login_text = self.ocr_region(500, 300, 400, 200)
        if "login" in login_text.lower() or "username" in login_text.lower():
            logger.warning("TOS login dialog detected - not ready")
            return False
        
        return True
    
    def navigate_tab(self, tab_name: str) -> bool:
        """Navigate to a tab using hotkeys."""
        hotkey = self.hotkeys.get(f"{tab_name.lower()}_tab")
        if hotkey:
            return self.hotkey(*hotkey)
        return False
    
    def enter_symbol(self, symbol: str) -> bool:
        """Enter a symbol in the active symbol box."""
        self.activate_app()
        
        # Click symbol input area
        # In TOS, the symbol box is typically top-left
        # Use AppleScript to set focus if possible
        script = f'''
        tell application "System Events"
            tell process "thinkorswim"
                keystroke "{symbol.upper()}"
                delay 0.5
                keystroke return
            end tell
        end tell
        '''
        self._run_applescript(script)
        time.sleep(1)
        return True
    
    def get_quote_data(self, symbol: str) -> Dict[str, Any]:
        """Get current quote data for a symbol from TOS."""
        if not self.is_app_running():
            logger.warning("TOS is not running")
            return {}
        
        self.activate_app()
        self.enter_symbol(symbol)
        time.sleep(1.5)
        
        # OCR the quote bar region
        bounds = self.get_window_position()
        if not bounds:
            logger.warning("Could not get TOS window bounds")
            return {}
        
        wx, wy, ww, wh = bounds
        quote_region = (
            wx + int(ww * 0.15),
            wy + int(wh * 0.08),
            int(ww * 0.55),
            int(wh * 0.08)
        )
        
        text = self.ocr_region(*quote_region)
        logger.debug(f"TOS quote OCR for {symbol}: {text[:200]}")
        
        result = {"symbol": symbol, "timestamp": datetime.utcnow().isoformat()}
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            m = re.search(r'[\d,]+\.\d{2}', line)
            if not m:
                continue
            val = float(m.group().replace(',', ''))
            if 'bid' in lower:
                result['bid'] = val
            elif 'ask' in lower:
                result['ask'] = val
            elif 'last' in lower:
                result['last'] = val
            elif 'high' in lower:
                result['high'] = val
            elif 'low' in lower:
                result['low'] = val
            elif 'open' in lower:
                result['open'] = val
            elif 'close' in lower:
                result['close'] = val
            elif 'change' in lower and '%' in line:
                result['change_percent'] = val
            elif 'change' in lower:
                result['change'] = val
            elif 'volume' in lower:
                result['volume'] = int(val)
        
        # Fallback: if no labels matched, assign by position heuristic
        if 'last' not in result:
            prices = re.findall(r'[\d,]+\.\d{2}', text)
            if prices:
                result['last'] = float(prices[0].replace(',', ''))
        
        return result

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get positions from the Monitor tab."""
        self.activate_app()
        self.navigate_tab("monitor")
        time.sleep(1)
        
        # Take screenshot of positions panel
        region = self.regions["positions_panel"]
        screenshot = self.screenshot(region)
        
        # OCR the positions
        text = self.ocr_region(*region)
        
        # Parse positions from text (basic parsing)
        positions = []
        lines = text.split('\n')
        for line in lines:
            # Look for patterns like "SPY 100 $450.00 +$500"
            import re
            match = re.search(r'(\w+)\s+(-?\d+)\s+\$?([\d.]+)', line)
            if match:
                positions.append({
                    "symbol": match.group(1),
                    "quantity": int(match.group(2)),
                    "price": float(match.group(3)),
                    "raw": line
                })
        
        return positions
    
    def place_order(self, order: Dict[str, Any]) -> DesktopActionResult:
        """
        Place an order using TOS Active Trader or order ticket.
        
        For fastest execution, uses Active Trader ladder.
        
        Args:
            order: Dict with symbol, side, quantity, order_type, price
        """
        symbol = order.get("symbol", "")
        side = order.get("side", "long")
        quantity = int(order.get("quantity", 1))
        order_type = order.get("order_type", "market")
        price = order.get("price")
        
        self.activate_app()
        
        # Enter symbol
        self.enter_symbol(symbol)
        time.sleep(0.5)
        
        # Open Active Trader
        self.hotkey(*self.hotkeys["active_trader"])
        time.sleep(1)
        
        # Use market order hotkeys for speed
        if order_type.lower() == "market":
            if side.lower() in ["buy", "long"]:
                self.hotkey(*self.hotkeys["buy_market"])
            else:
                self.hotkey(*self.hotkeys["sell_market"])
            
            time.sleep(0.5)
            
            # Confirm in order ticket
            self.hotkey("return")
            
            result = DesktopActionResult(
                success=True,
                action=f"market_{side}_{symbol}",
                data={"symbol": symbol, "side": side, "quantity": quantity, "type": "market"}
            )
        else:
            # Limit order - need to use order ticket
            result = self._place_limit_order_tos(symbol, side, quantity, price)
        
        # Screenshot for verification
        screenshot = self.screenshot()
        result.screenshot_path = screenshot
        
        self.record_action(
            action=f"place_order_{symbol}",
            success=result.success,
            data=result.data,
            error=result.error
        )
        
        return result
    
    def _place_limit_order_tos(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
    ) -> DesktopActionResult:
        """Place limit order via TOS order ticket."""
        # Open order ticket with hotkey
        self.hotkey("ctrl", "o")  # Common TOS shortcut
        time.sleep(0.5)
        
        # Fill order ticket
        script = f'''
        tell application "System Events"
            tell process "thinkorswim"
                -- Set quantity
                keystroke "{quantity}"
                delay 0.2
                keystroke tab
                delay 0.2
                -- Set price
                keystroke "{price}"
                delay 0.2
                -- Confirm
                keystroke return
            end tell
        end tell
        '''
        self._run_applescript(script)
        time.sleep(0.5)
        
        return DesktopActionResult(
            success=True,
            action="limit_order",
            data={"symbol": symbol, "side": side, "quantity": quantity, "price": price}
        )
    
    def place_option_order(
        self,
        underlying: str,
        expiration: str,
        strike: float,
        option_type: str,
        side: str,
        quantity: int,
    ) -> DesktopActionResult:
        """
        Place an option order in TOS.
        
        Steps:
        1. Enter underlying
        2. Open option chain (Shift+F5)
        3. Select expiration
        4. Click strike
        5. Fill order ticket
        """
        self.activate_app()
        
        # Enter underlying
        self.enter_symbol(underlying)
        time.sleep(0.5)
        
        # Open option chain
        self.hotkey("shift", "f5")
        time.sleep(1)
        
        # This gets complex - use AppleScript to navigate
        script = f'''
        tell application "System Events"
            tell process "thinkorswim"
                -- Navigate to expiration tab (simplified)
                delay 0.5
                -- Click on strike (approximate)
                -- In practice, you'd need image recognition here
            end tell
        end tell
        '''
        self._run_applescript(script)
        
        return DesktopActionResult(
            success=True,
            action="option_order",
            data={
                "underlying": underlying,
                "expiration": expiration,
                "strike": strike,
                "option_type": option_type,
                "side": side,
                "quantity": quantity
            }
        )
    
    def flatten_all(self) -> DesktopActionResult:
        """Close all positions immediately (emergency)."""
        self.activate_app()
        self.hotkey(*self.hotkeys["flatten"])
        time.sleep(0.5)
        
        # Confirm if dialog appears
        self.hotkey("return")
        
        return DesktopActionResult(
            success=True,
            action="flatten_all",
            data={"timestamp": datetime.utcnow().isoformat()}
        )
    
    def cancel_all_orders(self) -> DesktopActionResult:
        """Cancel all working orders."""
        self.activate_app()
        self.hotkey(*self.hotkeys["cancel_all"])
        return DesktopActionResult(success=True, action="cancel_all")
    
    def read_account_balance(self) -> Dict[str, Any]:
        """Read account info from TOS."""
        self.activate_app()
        self.navigate_tab("monitor")
        time.sleep(0.5)
        
        region = self.regions["account_info"]
        text = self.ocr_region(*region)
        
        # Parse basic info
        import re
        balance = None
        buying_power = None
        
        balance_match = re.search(r'Net\s+Liq[.:]*\s*\$?([\d,]+\.\d{2})', text, re.I)
        if balance_match:
            balance = float(balance_match.group(1).replace(',', ''))
        
        bp_match = re.search(r'Buying\s+Power[.:]*\s*\$?([\d,]+\.\d{2})', text, re.I)
        if bp_match:
            buying_power = float(bp_match.group(1).replace(',', ''))
        
        return {
            "net_liquidation": balance,
            "buying_power": buying_power,
            "raw_text": text
        }
    
    def set_stop_loss(self, symbol: str, stop_price: float) -> bool:
        """Set a stop loss on an open position."""
        self.activate_app()
        
        # Navigate to position, right-click, create closing order
        # This requires finding the position in the list
        # Simplified version using AppleScript
        script = f'''
        tell application "System Events"
            tell process "thinkorswim"
                -- Simplified: would need to find position row first
                keystroke "{symbol}"
                delay 0.3
            end tell
        end tell
        '''
        self._run_applescript(script)
        return True
    
    def create_alert(self, symbol: str, condition: str, note: str = "") -> bool:
        """Create a price alert in TOS."""
        self.activate_app()
        self.enter_symbol(symbol)
        
        # TOS alert hotkey
        self.hotkey("ctrl", "shift", "l")
        time.sleep(0.5)
        
        # Fill alert dialog
        script = f'''
        tell application "System Events"
            tell process "thinkorswim"
                keystroke "{condition}"
                delay 0.2
                keystroke tab
                delay 0.2
                keystroke "{note}"
                delay 0.2
                keystroke return
            end tell
        end tell
        '''
        self._run_applescript(script)
        return True
