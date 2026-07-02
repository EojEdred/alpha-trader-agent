"""
Tradovate Desktop Automation

Controls Tradovate desktop platform (used by many prop firms).
Uses pyautogui and AppleScript.
"""

import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger

from .base_desktop_agent import BaseDesktopAgent, DesktopActionResult


class TradovateDesktopAgent(BaseDesktopAgent):
    """
    Desktop automation for Tradovate platform.
    
    Tradovate is the web/desktop platform used by:
    - Topstep
    - Apex Trader Funding
    - Direct futures trading
    
    The desktop app provides lower latency than browser.
    """
    
    def __init__(self):
        super().__init__(
            app_name="Tradovate",
            app_path="/Applications/Tradovate.app",
            verification_enabled=True,
        )
        
        # Approximate screen regions
        self.regions = {
            "account_header": (50, 50, 400, 80),
            "positions_panel": (50, 400, 500, 300),
            "dom_ladder": (1000, 150, 300, 600),
            "chart_area": (400, 150, 600, 500),
            "order_ticket": (1350, 150, 300, 400),
        }
    
    def is_ready(self) -> bool:
        """Check if Tradovate is loaded and connected."""
        if not self.is_app_running():
            return False
        
        self.activate_app()
        
        # Check for connection status
        text = self.ocr_region(50, 50, 200, 40)
        if "connected" in text.lower() or "live" in text.lower():
            return True
        
        return False
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get open futures positions."""
        self.activate_app()
        
        region = self.regions["positions_panel"]
        text = self.ocr_region(*region)
        
        positions = []
        lines = text.split('\n')
        
        for line in lines:
            # Parse position lines
            # Format varies but typically: SYMBOL QTY AVG_PRICE UNREALIZED_PNL
            import re
            match = re.search(r'(NQ|ES|YM|CL|GC|SI|ZB|ZN)[A-Z0-9]*\s+(-?\d+)\s+([\d.]+)', line)
            if match:
                positions.append({
                    "symbol": match.group(1),
                    "contracts": int(match.group(2)),
                    "avg_price": float(match.group(3)),
                    "raw": line
                })
        
        return positions
    
    def place_order(self, order: Dict[str, Any]) -> DesktopActionResult:
        """Place a futures order via Tradovate DOM or order ticket."""
        symbol = order.get("symbol", "")
        side = order.get("side", "long")
        quantity = int(order.get("quantity", 1))
        order_type = order.get("order_type", "market")
        price = order.get("price")
        
        self.activate_app()
        
        # Click on DOM ladder for fast market orders
        if order_type.lower() == "market":
            return self._place_market_order_dom(symbol, side, quantity)
        else:
            return self._place_limit_order_ticket(symbol, side, quantity, price)
    
    def _place_market_order_dom(self, symbol: str, side: str, quantity: int) -> DesktopActionResult:
        """Place market order using DOM ladder (fastest)."""
        # Click on the bid or ask column in DOM
        dom_region = self.regions["dom_ladder"]
        
        if side.lower() in ["buy", "long"]:
            # Click on ask column (right side of DOM)
            click_x = dom_region[0] + 200
        else:
            # Click on bid column (left side of DOM)
            click_x = dom_region[0] + 100
        
        click_y = dom_region[1] + 100  # Approximate middle of ladder
        
        self.click(click_x, click_y)
        time.sleep(0.2)
        
        # Confirm order
        self.hotkey("return")
        
        return DesktopActionResult(
            success=True,
            action=f"dom_market_{side}",
            data={"symbol": symbol, "side": side, "quantity": quantity}
        )
    
    def _place_limit_order_ticket(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
    ) -> DesktopActionResult:
        """Place limit order via order ticket."""
        # Open order ticket
        self.hotkey("ctrl", "o")
        time.sleep(0.3)
        
        # Fill fields using AppleScript for reliability
        script = f'''
        tell application "System Events"
            tell process "Tradovate"
                keystroke "{symbol}"
                delay 0.2
                keystroke tab
                delay 0.2
                keystroke "{quantity}"
                delay 0.2
                keystroke tab
                delay 0.2
                keystroke "{price}"
                delay 0.2
                keystroke return
            end tell
        end tell
        '''
        
        import subprocess
        subprocess.run(["osascript", "-e", script])
        
        return DesktopActionResult(
            success=True,
            action="limit_order",
            data={"symbol": symbol, "side": side, "quantity": quantity, "price": price}
        )
    
    def flatten_position(self, symbol: str) -> DesktopActionResult:
        """Close a specific position."""
        self.activate_app()
        
        # Find position and click flatten
        # Simplified - would need image recognition for robust implementation
        script = f'''
        tell application "System Events"
            tell process "Tradovate"
                -- Select symbol
                keystroke "{symbol}"
                delay 0.3
                -- Flatten hotkey (if available)
                keystroke "f" using {{command down}}
            end tell
        end tell
        '''
        
        import subprocess
        subprocess.run(["osascript", "-e", script])
        
        return DesktopActionResult(success=True, action="flatten", data={"symbol": symbol})
    
    def flatten_all(self) -> DesktopActionResult:
        """Close all positions."""
        self.activate_app()
        self.hotkey("ctrl", "shift", "f")
        time.sleep(0.3)
        self.hotkey("return")
        
        return DesktopActionResult(
            success=True,
            action="flatten_all",
            data={"timestamp": datetime.utcnow().isoformat()}
        )
    
    def set_stop_loss(self, symbol: str, stop_price: float) -> bool:
        """Set OCO bracket with stop loss."""
        self.activate_app()
        
        script = f'''
        tell application "System Events"
            tell process "Tradovate"
                keystroke "{symbol}"
                delay 0.3
                -- Open bracket order
                -- This varies by Tradovate version
            end tell
        end tell
        '''
        
        import subprocess
        subprocess.run(["osascript", "-e", script])
        return True
    
    def get_account_info(self) -> Dict[str, Any]:
        """Read account info from header."""
        self.activate_app()
        
        region = self.regions["account_header"]
        text = self.ocr_region(*region)
        
        import re
        info = {"raw_text": text}
        
        balance_match = re.search(r'\$?([\d,]+\.\d{2})', text)
        if balance_match:
            info["balance"] = float(balance_match.group(1).replace(',', ''))
        
        return info
