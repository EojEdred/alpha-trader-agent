"""
TradingView Browser Agent

Automates TradingView web interface for:
- Chart analysis and indicator reading
- Order placement via TradingView's broker integrations
- Alert management
- Screenshot capture for visual analysis
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger

from .base_browser_agent import BaseBrowserAgent, BrowserActionResult


class TradingViewAgent(BaseBrowserAgent):
    """
    Autonomous TradingView browser agent.
    
    TradingView connects to brokers like:
    - Tradovate (futures)
    - TradeStation
    - Webull
    - Alpaca
    - OANDA
    - FXCM
    - Interactive Brokers (via web)
    
    This agent navigates TradingView and uses its trading panel
    to execute orders through whichever broker is connected.
    """
    
    def __init__(self, model: Optional[str] = None, dry_run: bool = False):
        super().__init__(
            platform_name="tradingview",
            model=model,
            headless=False,  # TradingView needs visible for some features
            slow_mo=150,
            dry_run=dry_run,
        )
        self.base_url = "https://www.tradingview.com"
        self._logged_in = False
    
    async def login(self, credentials: Dict[str, str]) -> BrowserActionResult:
        """Log into TradingView."""
        username = credentials.get("username")
        password = credentials.get("password")
        
        if not username or not password:
            return BrowserActionResult(
                success=False,
                action="login",
                error="Missing username or password"
            )
        
        result = await self.run_task(f"""
        Go to {self.base_url}/chart.
        
        If already logged in (no login button visible), just confirm and stop.
        
        If login button is visible:
        1. Click the "Sign in" button
        2. Choose "Email" option if prompted
        3. Enter username: {username}
        4. Enter password: {password}
        5. Click the Sign in button
        6. Wait for the chart to load
        7. Confirm successful login by checking for the account menu or user icon
        
        If 2FA/CAPTCHA appears, STOP and report it.
        """)
        
        self._logged_in = result.success
        return result
    
    async def navigate_to_symbol(self, symbol: str, timeframe: str = "1h") -> BrowserActionResult:
        """Navigate to a specific symbol and timeframe."""
        return await self.run_task(f"""
        On the TradingView chart:
        1. Click on the symbol/ticker input at the top
        2. Clear the current text (select all + delete)
        3. Type: {symbol}
        4. Press Enter
        5. Wait for the chart to load the new symbol
        6. Click the timeframe selector (shows current timeframe like "1h" or "D")
        7. Select "{timeframe}" from the dropdown
        8. Confirm the chart shows {symbol} on {timeframe} timeframe
        """)
    
    async def read_indicators(self) -> Dict[str, Any]:
        """Read visible indicator values from the chart."""
        result = await self.run_task("""
        On the TradingView chart, read all visible indicator values:
        - Current price (from the price scale on right)
        - RSI value (if RSI indicator is visible)
        - MACD values (if MACD is visible)
        - Volume (current candle)
        - Any other visible indicator values
        
        Return ONLY a JSON object:
        {
            "current_price": number,
            "rsi": number or null,
            "macd_line": number or null,
            "macd_signal": number or null,
            "macd_histogram": number or null,
            "volume": number or null,
            "sma_20": number or null,
            "sma_50": number or null,
            "sma_200": number or null,
            "ema_9": number or null,
            "vwap": number or null
        }
        """)
        
        if result.success:
            try:
                text = result.data.get("result", "")
                # Extract JSON from response
                json_start = text.find("{")
                json_end = text.rfind("}")
                if json_start >= 0 and json_end > json_start:
                    return json.loads(text[json_start:json_end+1])
            except Exception as e:
                logger.error(f"Failed to parse indicators: {e}")
        
        return {}
    
    async def place_order(self, order: Dict[str, Any]) -> BrowserActionResult:
        """
        Place an order through TradingView's trading panel.
        
        Args:
            order: Dict with symbol, side, quantity, order_type, price, stop_loss, take_profit
        
        Note: A broker must be connected in TradingView for this to work.
        """
        symbol = order.get("symbol", "")
        side = order.get("side", "long")
        quantity = int(order.get("quantity", 1))
        order_type = order.get("order_type", "market")
        price = order.get("price")
        stop_loss = order.get("stop_loss")
        take_profit = order.get("take_profit")
        
        order_type_upper = order_type.upper()
        side_lower = side.lower()
        
        # Use visual descriptions instead of text labels for robustness
        buy_btn_desc = "the green Buy button on the right side of the trading panel"
        sell_btn_desc = "the red Sell button on the right side of the trading panel"
        
        task = f"""
        On TradingView, place a {side_lower} order:
        
        1. Make sure the symbol is set to {symbol}
        2. Open the trading panel on the right side (click "Trading Panel" if not visible)
        3. Click the {buy_btn_desc if side_lower == 'long' else sell_btn_desc}
        4. Enter quantity: {quantity}
        5. Select order type: {order_type_upper}
        """
        
        if order_type_upper == "LIMIT" and price:
            task += f"6. Enter limit price: {price}\n"
        
        if stop_loss:
            task += f"7. Enter stop loss: {stop_loss}\n"
        
        if take_profit:
            task += f"8. Enter take profit: {take_profit}\n"
        
        task += """
        9. Click "Place Order" or "Submit"
        10. Wait for confirmation dialog
        11. Read and report:
            - Order ID
            - Fill price
            - Status (filled/pending/rejected)
            - Any error messages
        
        If a confirmation dialog appears, click "Yes" or "Confirm".
        """
        
        result = await self.run_task(task)
        
        # Take screenshot for verification
        if result.success:
            screenshot = await self.screenshot(f"tv_order_{symbol}_{datetime.utcnow().strftime('%H%M%S')}.png")
            result.screenshot_path = screenshot
        
        return result
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get open positions from TradingView's trading panel."""
        result = await self.run_task("""
        In TradingView's trading panel:
        1. Click on the "Positions" tab
        2. Read all open positions
        3. For each position, report:
           - Symbol
           - Side (Long/Short)
           - Quantity/Size
           - Entry Price
           - Current Price
           - Unrealized P&L
        
        Return ONLY a JSON array:
        [
            {"symbol": "...", "side": "long/short", "size": number, "entry": number, "current": number, "pnl": number}
        ]
        """)
        
        if result.success:
            try:
                text = result.data.get("result", "")
                json_start = text.find("[")
                json_end = text.rfind("]")
                if json_start >= 0 and json_end > json_start:
                    return json.loads(text[json_start:json_end+1])
            except Exception as e:
                logger.error(f"Failed to parse positions: {e}")
        
        return []
    
    async def close_position(self, symbol: str) -> BrowserActionResult:
        """Close a position through TradingView."""
        return await self.run_task(f"""
        In TradingView's trading panel:
        1. Find the position for {symbol}
        2. Click the "X" or "Close" button next to it
        3. Confirm the close order
        4. Report the close price and realized P&L
        """)
    
    async def create_alert(
        self,
        symbol: str,
        condition: str,
        message: str,
        webhook_url: Optional[str] = None,
    ) -> BrowserActionResult:
        """
        Create a TradingView alert.
        
        Args:
            condition: e.g., "price crosses above 450", "RSI > 70"
            webhook_url: Optional webhook URL for external notifications
        """
        task = f"""
        On TradingView for {symbol}:
        1. Click the "Alert" button (bell icon) at the top
        2. Set condition: {condition}
        3. Set message: {message}
        4. Set expiration: 1 week
        """
        
        if webhook_url:
            task += f"""
        5. In the Notifications section, enable "Webhook URL"
        6. Enter webhook URL: {webhook_url}
        """
        
        task += """
        7. Click "Create"
        8. Confirm the alert was created
        """
        
        return await self.run_task(task)
    
    async def read_account_info(self) -> Dict[str, Any]:
        """Read account balance and P&L from TradingView."""
        result = await self.run_task("""
        In TradingView's trading panel or account section:
        1. Read the account balance
        2. Read buying power/equity
        3. Read daily P&L
        4. Read total unrealized P&L
        
        Return ONLY a JSON object:
        {
            "balance": number,
            "buying_power": number,
            "daily_pnl": number,
            "unrealized_pnl": number,
            "currency": "USD"
        }
        """)
        
        if result.success:
            try:
                text = result.data.get("result", "")
                json_start = text.find("{")
                json_end = text.rfind("}")
                if json_start >= 0 and json_end > json_start:
                    return json.loads(text[json_start:json_end+1])
            except Exception:
                pass
        
        return {}
    
    async def scan_screener(self, screener_url: str) -> List[Dict[str, Any]]:
        """Scan a TradingView screener and extract results."""
        result = await self.run_task(f"""
        Go to {screener_url}
        
        1. Wait for the screener table to load
        2. Read the top 10 rows
        3. For each row, extract:
           - Symbol/Ticker
           - Price
           - Change %
           - Volume
           - Any other visible columns
        
        Return ONLY a JSON array of objects.
        """)
        
        if result.success:
            try:
                text = result.data.get("result", "")
                json_start = text.find("[")
                json_end = text.rfind("]")
                if json_start >= 0 and json_end > json_start:
                    return json.loads(text[json_start:json_end+1])
            except Exception:
                pass
        
        return []
