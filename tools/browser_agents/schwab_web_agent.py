"""
Schwab Web Agent

Browser automation for Charles Schwab web interface.
Used as fallback when schwab-py API can't handle complex orders (spreads, multi-leg).
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger

from .base_browser_agent import BaseBrowserAgent, BrowserActionResult


class SchwabWebAgent(BaseBrowserAgent):
    """
    Browser agent for Charles Schwab web interface.
    
    Use cases:
    - Complex options spreads (iron condors, butterflies)
    - Multi-leg option orders
    - Orders requiring conditional logic
    - When schwab-py API has issues
    
    NOTE: Schwab also has a mobile app and StreetSmart Edge desktop app,
    but the web interface is most accessible for automation.
    """
    
    def __init__(self, model: Optional[str] = None, dry_run: bool = False):
        super().__init__(
            platform_name="schwab_web",
            model=model,
            headless=False,
            slow_mo=200,
            dry_run=dry_run,
        )
        self.base_url = "https://client.schwab.com"
        self._logged_in = False
    
    async def login(self, credentials: Dict[str, str]) -> BrowserActionResult:
        """Log into Schwab web interface."""
        username = credentials.get("username")
        password = credentials.get("password")
        
        if not username or not password:
            return BrowserActionResult(
                success=False,
                action="login",
                error="Missing username or password"
            )
        
        result = await self.run_task(f"""
        Go to {self.base_url}
        
        1. Wait for the login page to load
        2. Find the login ID field (might be labeled "Login ID" or "Username")
        3. Enter: {username}
        4. Find the password field
        5. Enter: {password}
        6. Click the "Log In" button
        7. Wait for the account dashboard to load (up to 15 seconds)
        8. Confirm successful login by looking for:
           - Account summary
           - Portfolio value
           - Navigation menu
           - "Welcome" message
        
        If a security question appears, STOP and report "Security question required".
        If 2FA/SMS code is requested, STOP and report "2FA required".
        If CAPTCHA appears, STOP and report "CAPTCHA detected".
        """)
        
        self._logged_in = result.success
        return result
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions from Schwab."""
        result = await self.run_task("""
        On the Schwab dashboard:
        1. Click "Accounts" or "Portfolio" if not already visible
        2. Navigate to the Positions page
        3. Read all positions:
           - Stocks/ETFs
           - Options (with full option symbols)
           - Cash/money market
        
        For each position, report:
        - Symbol
        - Quantity
        - Current Price
        - Market Value
        - Unrealized P&L
        - Cost Basis (if visible)
        
        Return ONLY a JSON array.
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
    
    async def place_order(self, order: Dict[str, Any]) -> BrowserActionResult:
        """Generic order placement - delegates to specific method based on order type."""
        order_type = order.get("order_type", "equity")
        
        if order_type in ("equity", "stock", "etf"):
            return await self.place_equity_order(
                symbol=order["symbol"],
                side=order["side"],
                quantity=order["quantity"],
                order_type=order.get("type", "market"),
                price=order.get("price"),
                time_in_force=order.get("time_in_force", "day"),
            )
        elif order_type in ("option", "single_option"):
            return await self.place_option_order(
                underlying=order["underlying"],
                option_symbol=order["option_symbol"],
                side=order["side"],
                quantity=order["quantity"],
                order_type=order.get("type", "limit"),
                price=order.get("price"),
            )
        elif order_type in ("spread", "multi_leg", "iron_condor"):
            return await self.place_option_spread(
                underlying=order["underlying"],
                spread_type=order.get("spread_type", "Custom Spread"),
                legs=order["legs"],
                quantity=order["quantity"],
                net_credit_or_debit=order.get("net_credit_or_debit", 0.0),
            )
        else:
            return BrowserActionResult(
                success=False,
                action="place_order",
                error=f"Unknown order type: {order_type}"
            )
    
    async def place_equity_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "market",
        price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> BrowserActionResult:
        """Place a simple equity order."""
        side_upper = side.upper()
        order_type_upper = order_type.upper()
        
        return await self.run_task(f"""
        On Schwab:
        1. Click "Trade" in the navigation
        2. Select the account (first account if multiple)
        3. Enter symbol: {symbol}
        4. Select action: {'Buy' if side_upper == 'BUY' else 'Sell'}
        5. Enter quantity: {quantity}
        6. Select order type: {order_type_upper}
        """
        + (f"7. Enter limit price: {price}\n" if order_type_upper == "LIMIT" and price else "")
        + f"""
        8. Select time in force: {time_in_force}
        9. Click "Review Order"
        10. On the review page, verify all details are correct
        11. Click "Place Order"
        12. Wait for confirmation
        13. Report:
            - Order number
            - Status (filled/working/rejected)
            - Any messages
        """)
    
    async def place_option_order(
        self,
        underlying: str,
        option_symbol: str,
        side: str,  # buy_to_open, sell_to_close, etc.
        quantity: int,
        order_type: str = "limit",
        price: Optional[float] = None,
    ) -> BrowserActionResult:
        """Place a single-leg option order."""
        return await self.run_task(f"""
        On Schwab:
        1. Click "Trade" → "Options"
        2. Enter underlying symbol: {underlying}
        3. View the option chain
        4. Find the option: {option_symbol}
        5. Click the bid or ask to start an order
        6. Select action: {side.replace('_', ' ').title()}
        7. Enter quantity: {quantity}
        8. Select order type: {order_type.upper()}
        """
        + (f"9. Enter price: {price}\n" if price else "")
        + """
        10. Click "Review Order"
        11. Verify details
        12. Click "Place Order"
        13. Report order number and status
        """)
    
    async def place_option_spread(
        self,
        underlying: str,
        spread_type: str,  # iron_condor, credit_spread, debit_spread, etc.
        legs: List[Dict[str, Any]],
        quantity: int,
        net_credit_or_debit: float,
    ) -> BrowserActionResult:
        """
        Place a multi-leg option spread.
        
        This is where the web agent shines - complex spreads are hard via API.
        
        Args:
            legs: List of leg dicts with keys:
                - side: buy/sell
                - option_type: call/put
                - strike: float
                - expiration: str (MM/DD/YYYY)
        """
        legs_desc = "\n".join([
            f"   Leg {i+1}: {leg['side'].title()} {leg['option_type'].title()} @ ${leg['strike']} exp {leg['expiration']}"
            for i, leg in enumerate(legs)
        ])
        
        return await self.run_task(f"""
        On Schwab, place a {spread_type} on {underlying}:
        
        1. Go to Trade → Options
        2. Enter underlying: {underlying}
        3. View option chain
        4. Look for "Spread" or "Multi-leg" order type and select it
        5. Build the spread with these legs:
        {legs_desc}
        6. Enter quantity: {quantity}
        7. Enter net credit/debit: {net_credit_or_debit}
        8. Click "Review Order"
        9. Carefully verify all legs are correct
        10. Click "Place Order"
        11. Report:
            - Order number
            - Status
            - Net premium received/paid
        """)
    
    async def place_iron_condor(
        self,
        underlying: str,
        expiration: str,
        put_sell_strike: float,
        put_buy_strike: float,
        call_sell_strike: float,
        call_buy_strike: float,
        quantity: int,
        net_credit: float,
    ) -> BrowserActionResult:
        """Place an iron condor - the classic income strategy."""
        return await self.place_option_spread(
            underlying=underlying,
            spread_type="Iron Condor",
            legs=[
                {"side": "sell", "option_type": "put", "strike": put_sell_strike, "expiration": expiration},
                {"side": "buy", "option_type": "put", "strike": put_buy_strike, "expiration": expiration},
                {"side": "sell", "option_type": "call", "strike": call_sell_strike, "expiration": expiration},
                {"side": "buy", "option_type": "call", "strike": call_buy_strike, "expiration": expiration},
            ],
            quantity=quantity,
            net_credit_or_debit=net_credit,
        )
    
    async def get_option_chain(self, symbol: str) -> List[Dict[str, Any]]:
        """Read option chain from Schwab web."""
        result = await self.run_task(f"""
        On Schwab:
        1. Go to Trade → Options
        2. Enter symbol: {symbol}
        3. View the option chain
        4. Read the first 3 expiration dates
        5. For each expiration, read the ATM call and put:
           - Strike
           - Bid
           - Ask
           - Volume
           - Open Interest
           - Implied Volatility (if shown)
        
        Return ONLY a JSON array of options.
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
    
    async def cancel_order(self, order_id: str) -> BrowserActionResult:
        """Cancel an open order."""
        return await self.run_task(f"""
        On Schwab:
        1. Go to Accounts → Orders
        2. Find order {order_id}
        3. Click "Cancel" next to it
        4. Confirm the cancellation
        5. Report the cancellation status
        """)
    
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Check status of an order."""
        result = await self.run_task(f"""
        On Schwab:
        1. Go to Accounts → Orders
        2. Find order {order_id}
        3. Read its status:
           - Status (working/filled/partial/cancelled/rejected)
           - Filled quantity
           - Remaining quantity
           - Average fill price
           - Time submitted
        
        Return ONLY a JSON object.
        """)
        
        if result.success:
            try:
                text = result.data.get("result", "")
                json_start = text.find("{")
                json_end = text.rfind("}")
                if json_start >= 0:
                    return json.loads(text[json_start:json_end+1])
            except Exception:
                pass
        
        return {}
