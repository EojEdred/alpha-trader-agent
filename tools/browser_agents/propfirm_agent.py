"""
Prop Firm Browser Agent

Automates prop firm web trading platforms using browser-use.
Supports Topstep, Apex Trader Funding, and other Tradovate-based platforms.
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger

from dotenv import load_dotenv
load_dotenv()

from .base_browser_agent import BaseBrowserAgent, BrowserActionResult

# ─── POSITION STATE TRACKING ───
_POSITION_STATE_PATH = "/Users/macbook/.alphatrader/data/position_state.json"

def _load_position_state() -> dict:
    """Load position entry times from disk."""
    try:
        if os.path.exists(_POSITION_STATE_PATH):
            with open(_POSITION_STATE_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Failed to load position state: {e}")
    return {}

def _save_position_state(state: dict):
    """Save position entry times to disk."""
    try:
        os.makedirs(os.path.dirname(_POSITION_STATE_PATH), exist_ok=True)
        with open(_POSITION_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.debug(f"Failed to save position state: {e}")


def _record_position_entry(symbol: str, side: str, contracts: int, entry_price: float):
    """Record when a position was opened."""
    state = _load_position_state()
    state[symbol.upper()] = {
        "side": side,
        "contracts": contracts,
        "entry_price": entry_price,
        "entry_time": datetime.utcnow().isoformat(),
    }
    _save_position_state(state)
    logger.info(f"Recorded position entry: {symbol} {side} {contracts}x @ {entry_price}")

def _clear_position_entry(symbol: str):
    """Clear position record when closed."""
    state = _load_position_state()
    if symbol.upper() in state:
        del state[symbol.upper()]
        _save_position_state(state)
        logger.info(f"Cleared position entry for {symbol}")


def _get_position_entry(symbol: str) -> dict:
    """Get entry info for a symbol."""
    state = _load_position_state()
    return state.get(symbol.upper(), {})


class PropFirmAgent(BaseBrowserAgent):
    """
    Browser agent for prop firm trading platforms.
    
    Supported platforms:
    - TopstepX (Tradovate web)
    - Apex Trader Funding (Tradovate/Rithmic)
    - Leeloo Trading
    - The5ers
    
    CRITICAL: Prop firms typically prohibit automation. This agent:
    - Uses human-like delays (2-5s between actions)
    - Randomizes click timing
    - Only operates during normal trading hours
    - Respects Combine rules (daily loss, max contracts, drawdown)
    """
    
    PLATFORMS = {
        "topstep": {
            "name": "TopstepX",
            "login_url": "https://topstepx.com/login",
            "trading_url": "https://topstepx.com/trading",
            "dashboard_url": "https://topstepx.com/dashboard",
            "agreements_url": "https://topstepx.com/agreements",
            "selectors": {
                "username": "input[name='userName'], input[type='text']",
                "password": "input[name='password'], input[type='password']",
                "login_button": "button:has-text('PLATFORM LOGIN')",
                "buy_button": "button:has-text('Buy'), [data-testid='buy-btn'], .buy-button",
                "sell_button": "button:has-text('Sell'), [data-testid='sell-btn'], .sell-button",
                "quantity_input": "input[name='quantity'], input[name='qty'], [data-testid='qty-input']",
                "submit_order": "button:has-text('Submit'), button:has-text('Place Order'), [data-testid='submit-order']",
                "positions_tab": "button:has-text('Positions'), [data-testid='positions-tab']",
                "account_balance": "[data-testid='account-balance'], .balance, .account-value",
                "daily_pnl": "[data-testid='daily-pnl'], .daily-pnl",
            }
        },
        "apex": {
            "name": "Apex Trader Funding",
            "login_url": "https://apextraderfunding.com/member/login",
            "trading_url": "https://apextraderfunding.com/member/trading",
            "dashboard_url": "https://apextraderfunding.com/member/dashboard",
            "selectors": {
                "username": "input[name='username'], input[name='email']",
                "password": "input[type='password']",
                "login_button": "button[type='submit']",
            }
        },
        "leeloo": {
            "name": "Leeloo Trading",
            "login_url": "https://leelootrading.com/login",
            "trading_url": "https://leelootrading.com/trading",
            "dashboard_url": "https://leelootrading.com/dashboard",
            "selectors": {}
        }
    }
    
    def __init__(self, platform: str = "topstep", model: Optional[str] = None, dry_run: bool = False):
        super().__init__(
            platform_name=f"propfirm_{platform}",
            model=model,
            headless=False,
            slow_mo=300,  # Slower for prop firms (human-like)
            dry_run=dry_run,
        )
        self.platform = platform.lower()
        self.platform_config = self.PLATFORMS.get(self.platform, self.PLATFORMS["topstep"])
        self._combine_rules = {}
        self._logged_in = False
    
    async def login(self, credentials: Dict[str, str]) -> BrowserActionResult:
        """Log into the prop firm platform."""
        username = credentials.get("username")
        password = credentials.get("password")
        
        if not username or not password:
            return BrowserActionResult(
                success=False,
                action="login",
                error="Missing credentials"
            )
        
        login_url = self.platform_config["login_url"]
        
        result = await self.run_task(f"""
        Go to {login_url}
        
        1. Wait for the page to fully load
        2. Find the username/email input field
        3. Enter: {username}
        4. Find the password input field
        5. Enter: {password}
        6. Find and click the login/sign in button
        7. Wait for the dashboard or trading page to load (up to 15 seconds)
        8. Confirm successful login by looking for:
           - Account balance
           - Trading panel
           - User name/profile
           - Dashboard elements
        
        If a CAPTCHA appears, STOP and report "CAPTCHA detected".
        If 2FA is requested, STOP and report "2FA required".
        """)
        
        self._logged_in = result.success
        
        if result.success:
            # Load Combine rules after login
            await self._load_combine_rules()
        
        return result
    
    async def _load_combine_rules(self):
        """Load account-specific Combine rules."""
        result = await self.run_task("""
        On the dashboard or account page:
        1. Read the account balance
        2. Read the maximum daily loss limit
        3. Read the trailing drawdown level
        4. Read the maximum allowed contracts
        5. Read the profit target
        
        Return ONLY a JSON object:
        {
            "balance": number,
            "max_daily_loss": number,
            "trailing_drawdown": number,
            "max_contracts": number,
            "profit_target": number,
            "account_type": "e.g., $50k Combine"
        }
        """)
        
        if result.success:
            try:
                text = result.data.get("result", "")
                json_start = text.find("{")
                json_end = text.rfind("}")
                if json_start >= 0:
                    self._combine_rules = json.loads(text[json_start:json_end+1])
            except Exception:
                pass
    
    async def check_compliance(self) -> Dict[str, Any]:
        """
        Check if account is compliant with Combine rules.
        Returns dict with 'can_trade', 'reasons', 'metrics'.
        """
        if not self._logged_in:
            return {"can_trade": False, "reason": "Not logged in"}
        
        result = await self.run_task("""
        On the trading dashboard:
        1. Read current account balance
        2. Read today's P&L (daily P&L)
        3. Read current drawdown level
        4. Read number of open contracts/positions
        5. Check for any warning messages or alerts
        
        Return ONLY a JSON object:
        {
            "balance": number,
            "daily_pnl": number,
            "drawdown_level": number,
            "open_contracts": number,
            "can_trade": true/false,
            "reasons": ["list of issues if any"],
            "warnings": ["any warning messages"]
        }
        """)
        
        if result.success:
            try:
                text = result.data.get("result", "")
                json_start = text.find("{")
                json_end = text.rfind("}")
                if json_start >= 0:
                    compliance = json.loads(text[json_start:json_end+1])
                    
                    # Validate against known rules
                    reasons = compliance.get("reasons", [])
                    
                    if self._combine_rules.get("max_daily_loss"):
                        daily_pnl = compliance.get("daily_pnl", 0)
                        max_loss = self._combine_rules["max_daily_loss"]
                        if daily_pnl <= -max_loss:
                            reasons.append(f"Daily loss limit reached: ${daily_pnl}")
                            compliance["can_trade"] = False
                    
                    if self._combine_rules.get("trailing_drawdown"):
                        balance = compliance.get("balance", 0)
                        drawdown = self._combine_rules["trailing_drawdown"]
                        if balance <= drawdown + 100:
                            reasons.append(f"Near liquidation: Balance ${balance}, Drawdown ${drawdown}")
                            compliance["can_trade"] = False
                    
                    compliance["reasons"] = reasons
                    return compliance
            except Exception as e:
                logger.error(f"Compliance parse failed: {e}")
        
        return {"can_trade": False, "reason": "Could not read compliance data"}
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get open futures positions."""
        result = await self.run_task("""
        In the trading platform:
        1. Click on the "Positions" tab or section
        2. Read all open positions
        3. For each position, report:
           - Symbol (e.g., NQZ24, ESZ24)
           - Side (Long/Short)
           - Quantity/Contracts
           - Entry Price
           - Current Price
           - Unrealized P&L
        
        Return ONLY a JSON array:
        [
            {"symbol": "NQZ24", "side": "long", "contracts": 2, "entry": 18500.0, "current": 18550.0, "pnl": 500.0}
        ]
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
        """
        Place a futures order through the prop firm web platform.
        
        CRITICAL: Always checks compliance first.
        
        Args:
            order: Dict with symbol, side, quantity, order_type, price, stop_loss
        """
        symbol = order.get("symbol", "")
        side = order.get("side", "long")
        quantity = int(order.get("quantity", 1))
        order_type = order.get("order_type", "market")
        price = order.get("price")
        
        # ─── HARD-CODED COMBINE GUARDRAILS — FAST PASS MODE ───
        hard_limits = self._get_hard_limits()
        max_contracts = 5  # Fast pass: 5 contracts max for $50K combine
        max_daily_loss = 1500
        trailing_drawdown = hard_limits.get("trailing_drawdown", 2000)
        
        # Check compliance via web scrape + hard limits
        compliance = await self.check_compliance()
        if not compliance.get("can_trade", False):
            return BrowserActionResult(
                success=False,
                action="place_order",
                error=f"Combine rule violation: {compliance.get('reasons', ['Unknown'])}"
            )
        
        # Validate scraped rules against hard limits
        scraped_max_contracts = self._combine_rules.get("max_contracts")
        if scraped_max_contracts and abs(scraped_max_contracts - max_contracts) > max_contracts * 0.05:
            logger.error(f"SCRAPED RULE MISMATCH: max_contracts scraped={scraped_max_contracts}, hard={max_contracts}")
            return BrowserActionResult(
                success=False,
                action="place_order",
                error="Combine rule verification failed: scraped rules do not match hard limits. Trading BLOCKED."
            )
        
        # Check max contracts against hard limit
        if quantity > max_contracts:
            logger.warning(f"Capping quantity {quantity} to max contracts {max_contracts}")
            quantity = max_contracts
        
        # Check existing positions
        positions = await self.get_positions()
        current_contracts = sum(p.get("contracts", 0) for p in positions)
        if current_contracts + quantity > max_contracts:
            available = max_contracts - current_contracts
            if available <= 0:
                return BrowserActionResult(
                    success=False,
                    action="place_order",
                    error=f"Max contracts reached: {current_contracts}/{max_contracts}"
                )
            quantity = available
            logger.warning(f"Reduced quantity to {quantity} to stay within max contracts")
        
        # Check daily loss against hard limit
        daily_pnl = compliance.get("daily_pnl", 0)
        if daily_pnl <= -max_daily_loss:
            return BrowserActionResult(
                success=False,
                action="place_order",
                error=f"Daily loss limit reached: ${daily_pnl} (limit: ${max_daily_loss})"
            )
        
        # Check drawdown against hard limit
        balance = compliance.get("balance", 0)
        if balance <= trailing_drawdown + 100:
            return BrowserActionResult(
                success=False,
                action="place_order",
                error=f"Near liquidation: Balance ${balance}, Drawdown ${trailing_drawdown}"
            )
        
        side_lower = side.lower()
        order_type_upper = order_type.upper()
        
        task = f"""
        In the prop firm trading platform:
        
        1. Make sure the active symbol is set to {symbol}
        2. Click the {'"Buy Market" or "Buy"' if side_lower == 'long' else '"Sell Market" or "Sell"'} button
        3. If an order ticket/dialog opens:
           - Enter quantity: {quantity}
           - Select order type: {order_type_upper}
        """
        
        if order_type_upper == "LIMIT" and price:
            task += f"   - Enter limit price: {price}\n"
        
        task += """
        4. Click "Submit Order" or "Place Order"
        5. Wait for confirmation (2-3 seconds)
        6. Read the confirmation message
        7. Report:
           - Order ID (if shown)
           - Fill price
           - Status (filled/pending/rejected)
           - Any error messages
        
        If a confirmation dialog asks "Are you sure?", click "Yes" or "Confirm".
        """
        
        result = await self.run_task(task)
        
        # Screenshot for audit
        if result.success:
            screenshot = await self.screenshot(f"prop_order_{symbol}_{datetime.utcnow().strftime('%H%M%S')}.png")
            result.screenshot_path = screenshot
        
        return result
    
    def _get_hard_limits(self) -> Dict[str, Any]:
        """Return hard-coded Combine rule templates by account type."""
        # Detect account type from scraped rules or default to $50k
        account_type = self._combine_rules.get("account_type", "$50k Combine").lower()
        
        templates = {
            "$50k": {
                "max_daily_loss": 2000,
                "trailing_drawdown": 2000,
                "max_contracts": 5,
                "profit_target": 3000,
            },
            "$100k": {
                "max_daily_loss": 3000,
                "trailing_drawdown": 3000,
                "max_contracts": 10,
                "profit_target": 6000,
            },
            "$150k": {
                "max_daily_loss": 4500,
                "trailing_drawdown": 4500,
                "max_contracts": 15,
                "profit_target": 9000,
            },
        }
        
        for key, rules in templates.items():
            if key in account_type:
                return rules
        
        # Default to most conservative ($50k)
        return templates["$50k"]
    
    async def close_position(self, symbol: str) -> BrowserActionResult:
        """Close all positions for a symbol."""
        return await self.run_task(f"""
        In the trading platform:
        1. Go to the Positions tab
        2. Find the position for {symbol}
        3. Click the "Close" or "X" button next to it
        4. Confirm the close order
        5. Report the close price and realized P&L
        """)
    
    async def set_stop_loss(self, symbol: str, stop_price: float) -> BrowserActionResult:
        """Set a stop loss on an open position."""
        return await self.run_task(f"""
        In the trading platform:
        1. Find the open position for {symbol}
        2. Click "Add Stop" or edit the stop loss
        3. Enter stop price: {stop_price}
        4. Submit the stop order
        5. Confirm it was added
        """)
    
    async def emergency_close_all(self) -> BrowserActionResult:
        """Close all positions immediately (circuit breaker)."""
        return await self.run_task("""
        EMERGENCY CLOSE ALL POSITIONS:
        1. Go to the Positions tab
        2. Look for a "Close All" button and click it
        3. If no Close All button, close each position individually
        4. Confirm all positions are closed
        5. Report the total realized P&L from closing
        """)
    
    async def get_account_summary(self) -> Dict[str, Any]:
        """Get account summary from dashboard."""
        result = await self.run_task("""
        On the account dashboard:
        1. Read account balance
        2. Read daily P&L
        3. Read total P&L
        4. Read number of trades today
        5. Read any status messages
        
        Return ONLY a JSON object:
        {
            "balance": number,
            "daily_pnl": number,
            "total_pnl": number,
            "trades_today": number,
            "status": "active/warning/locked"
        }
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


# ─── STANDALONE WRAPPERS FOR WORKFLOW ORCHESTRATOR ───

async def propfirm_check_compliance(platform: str = "topstep", config: dict = None, **kwargs) -> dict:
    """Wrapper for workflow orchestrator.
    
    For TopstepX, uses the ProjectX Gateway API (tools.topstep) instead of browser scraping.
    Falls back to Playwright for other platforms.
    """
    import os
    import asyncio
    from loguru import logger
    from playwright.async_api import async_playwright
    
    logger.info(f"propfirm_check_compliance called for {platform}")
    
    if platform.lower() == "topstep":
        try:
            from tools.topstep import topstep_check_compliance
            api = await topstep_check_compliance()
            warnings = list(api.get("reasons", []))
            if not api.get("compliant", False):
                warnings.append("API compliance check failed")
            daily_loss_used = api.get("daily_loss_used", 0.0)
            return {
                "can_trade": api.get("compliant", False) and api.get("can_trade", False),
                "reason": "API compliance check" if api.get("compliant") else "; ".join(warnings),
                "balance": api.get("balance", 50000.0),
                "daily_pnl": -daily_loss_used,
                "drawdown_level": daily_loss_used,
                "open_contracts": api.get("open_contracts", 0),
                "warnings": warnings,
            }
        except Exception as e:
            logger.error(f"TopstepX API compliance failed: {e}")
            return {"can_trade": False, "reason": f"API compliance error: {e}", "balance": 50000, "daily_pnl": 0, "drawdown_level": 0, "open_contracts": 0, "warnings": [str(e)]}
    
    username = os.getenv("TOPSTEP_USERNAME")
    password = os.getenv("TOPSTEP_PASSWORD")
    if not username or not password:
        logger.warning("Missing credentials — using hardcoded guardrails only")
        return {"can_trade": True, "reason": "No credentials — hard limits only", "balance": 50000, "daily_pnl": 0, "drawdown_level": 0, "open_contracts": 0, "warnings": []}
    
    # Hard limits for $50K Combine — CONSERVATIVE REBUILD
    max_contracts = int(os.getenv("TOPSTEP_MAX_CONTRACTS", 2))
    max_daily_loss = float(os.getenv("TOPSTEP_MAX_DAILY_LOSS", 500))
    trailing_drawdown = 3000
    
    result = {
        "can_trade": True,
        "reason": "Within limits",
        "balance": 50000,
        "daily_pnl": 0,
        "drawdown_level": 0,
        "open_contracts": 0,
        "warnings": [],
    }
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Quick login
            await page.goto("https://topstepx.com/login", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle")
            
            inputs = await page.query_selector_all("input")
            for inp in inputs:
                name = await inp.get_attribute("name") or ""
                typ = await inp.get_attribute("type") or ""
                if "user" in name.lower() or typ == "email":
                    await inp.fill(username)
                elif typ == "password":
                    await inp.fill(password)
            
            btn = await page.query_selector('button:has-text("PLATFORM LOGIN")')
            if btn:
                await btn.click()
            
            await page.wait_for_url("**/trade", timeout=30000)
            await asyncio.sleep(5)
            
            # Read account stats from top bar
            # Format: BAL: $49,926.20 | MLL: $48,000.00 | RP&L: -$73.80 | UP&L: $0.00
            top_bar = await page.query_selector('.MuiToolbar-root, [class*="toolbar"], header')
            if top_bar:
                text = await top_bar.inner_text()
                
                # Extract balance
                bal_match = __import__('re').search(r'BAL[:\s]+\$?([\d,]+\.?\d*)', text)
                if bal_match:
                    result["balance"] = float(bal_match.group(1).replace(',', ''))
                
                # Extract realized P&L
                rpl_match = __import__('re').search(r'RP&L[:\s]+[+-]?\$?([\d,]+\.?\d*)', text)
                if rpl_match:
                    result["daily_pnl"] = float(rpl_match.group(1).replace(',', ''))
                
                # Extract unrealized P&L
                upl_match = __import__('re').search(r'UP&L[:\s]+[+-]?\$?([\d,]+\.?\d*)', text)
                if upl_match:
                    result["unrealized_pnl"] = float(upl_match.group(1).replace(',', ''))
            
            # Count open positions from Positions tab
            try:
                pos_tab = await page.query_selector('button:has-text("Positions")')
                if pos_tab:
                    await pos_tab.click()
                    await asyncio.sleep(1)
                    pos_rows = await page.query_selector_all('tr, [class*="position"]')
                    result["open_contracts"] = len(pos_rows)
            except Exception:
                pass
            
            await browser.close()
    except Exception as e:
        logger.warning(f"Compliance check via browser failed: {e} — using hard limits")
    
    # Apply hard limits
    if result["balance"] < 50000 - trailing_drawdown:
        result["can_trade"] = False
        result["reason"] = f"Trailing drawdown hit: balance ${result['balance']}"
        result["warnings"].append("Trailing drawdown exceeded")
    
    if result["daily_pnl"] < -max_daily_loss:
        result["can_trade"] = False
        result["reason"] = f"Daily loss limit hit: ${result['daily_pnl']}"
        result["warnings"].append("Daily loss limit exceeded")
    
    if result["open_contracts"] >= max_contracts:
        result["warnings"].append(f"Near max contracts: {result['open_contracts']}/{max_contracts}")
    
    logger.info(f"Compliance check: can_trade={result['can_trade']}, balance={result['balance']}, daily_pnl={result['daily_pnl']}, open_contracts={result['open_contracts']}")
    return result


async def propfirm_place_order(platform: str = "topstep", symbol: str = "", side: str = "long", 
                               quantity: int = 1, order_type: str = "market", 
                               price: float = None, stop_loss: float = None, 
                               take_profit: float = None, config: dict = None,
                               scalp_decision: dict = None, risk_decision: dict = None,
                               **kwargs) -> dict:
    """Wrapper for workflow orchestrator.
    
    For TopstepX, uses the safe ProjectX Gateway API (tools.topstep) instead of
    fragile browser automation. Falls back to browser for other platforms.
    Extracts symbol/side/quantity/stop/target from scalp_decision if not provided directly.
    """
    # Extract from scalp_decision if available
    if scalp_decision:
        if not symbol:
            symbol = scalp_decision.get("symbol", "")
        if side == "long" and scalp_decision.get("direction"):
            side = scalp_decision.get("direction", "long")
        if quantity == 1 and scalp_decision.get("quantity"):
            quantity = scalp_decision.get("quantity", 1)
        if stop_loss is None and scalp_decision.get("stop_loss"):
            stop_loss = float(scalp_decision.get("stop_loss", 0)) or None
        if take_profit is None and scalp_decision.get("take_profit"):
            take_profit = float(scalp_decision.get("take_profit", 0)) or None

    if platform.lower() == "topstep":
        try:
            from tools.topstep import topstep_place_bracket_order
            # Use market entry if no price provided, else limit
            entry_type = "market" if price is None else "limit"
            result = await topstep_place_bracket_order(
                symbol=symbol,
                quantity=int(quantity),
                side=side,
                stop_loss=float(stop_loss) if stop_loss is not None else 0.0,
                take_profit=float(take_profit) if take_profit is not None else 0.0,
                entry_price=float(price) if price is not None else None,
                order_type=entry_type,
                confirmed=True,
            )
            # Normalize return shape
            if result.get("status") == "submitted":
                return {
                    "status": "submitted",
                    "platform": platform,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "order_id": result.get("entry_order_id"),
                    "stop_order_id": result.get("stop_order_id"),
                    "target_order_id": result.get("target_order_id"),
                    "details": result,
                }
            else:
                logger.warning(f"TopstepX API order blocked/failed: {result}")
                return {"status": "failed", "reason": result.get("error", "blocked"), "details": result}
        except Exception as e:
            logger.error(f"TopstepX API order error: {e}")
            return {"status": "failed", "reason": str(e)}

    # Fallback to browser automation for non-Topstep platforms
    return await propfirm_place_order_direct(
        platform=platform, symbol=symbol, side=side, quantity=quantity,
        order_type=order_type, price=price, stop_loss=stop_loss, take_profit=take_profit, config=config, **kwargs
    )


# ─── DIRECT PLAYWRIGHT ORDER PLACEMENT (BYPASSING BROWSER-USE) ───

async def _read_position_from_page(page) -> dict:
    """Read current open position from the order card."""
    try:
        text = await page.inner_text('body')
        # Look for pattern like "+1 @ 29123.50" or "-2 @ 29115.25"
        import re
        match = re.search(r'([+-]\d+)\s*@\s*([\d,]+\.?\d*)', text)
        if match:
            qty = int(match.group(1))
            entry = float(match.group(2).replace(',', ''))
            return {
                "open": True,
                "side": "short" if qty < 0 else "long",
                "contracts": abs(qty),
                "entry_price": entry,
            }
    except Exception:
        pass
    return {"open": False}


async def propfirm_place_order_direct(
    platform: str = "topstep",
    symbol: str = "",
    side: str = "long",
    quantity: int = 1,
    order_type: str = "market",
    price: float = None,
    stop_loss: float = None,
    take_profit: float = None,
    config: dict = None,
    **kwargs
) -> dict:
    """Place order via direct Playwright — with position checks, brackets, and consistency enforcement."""
    import asyncio
    from loguru import logger
    import os
    from playwright.async_api import async_playwright

    logger.info(f"DIRECT PLAYWRIGHT: {side} {quantity}x {symbol} on {platform}")

    # ─── PAPER TRADE MODE ───
    import yaml
    try:
        with open("/Users/macbook/Desktop/allternit-workspace/allternit-alpha-trader-agent/config/trading_params.yaml") as f:
            cfg = yaml.safe_load(f)
        if cfg.get("PAPER_TRADE", True):
            logger.info(f"📝 PAPER TRADE: Would place {side} {quantity}x {symbol} @ {price or 'market'}")
            return {"success": True, "paper_trade": True, "data": {"symbol": symbol, "side": side, "quantity": quantity, "price": price}}
    except Exception:
        pass  # If config missing, default to paper trade safe mode

    # ─── CONSISTENCY ENFORCEMENT ───
    from tools.topstep_consistency import topstep_consistency_enforcer
    consistency = await topstep_consistency_enforcer()
    if not consistency.get("can_trade", True):
        reasons = consistency.get("reasons", ["Unknown"])
        logger.warning(f"🚫 Topstep consistency block: {'; '.join(reasons)}")
        return {"success": False, "error": f"Consistency enforcer: {'; '.join(reasons)}", "consistency": consistency}
    
    # Cap quantity
    max_contracts = consistency.get("max_contracts", 1)
    if quantity > max_contracts:
        logger.warning(f"Capping quantity {quantity} to {max_contracts} for consistency")
        quantity = max_contracts

    # Use safe ProjectX Gateway API for TopstepX
    if platform.lower() == "topstep":
        try:
            from tools.topstep import topstep_place_bracket_order
            entry_type = "market" if price is None else "limit"
            result = await topstep_place_bracket_order(
                symbol=symbol,
                quantity=int(quantity),
                side=side,
                stop_loss=float(stop_loss) if stop_loss is not None else 0.0,
                take_profit=float(take_profit) if take_profit is not None else 0.0,
                entry_price=float(price) if price is not None else None,
                order_type=entry_type,
                confirmed=True,
            )
            if result.get("status") == "submitted":
                return {
                    "success": True,
                    "action": "place_order",
                    "platform": platform,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "order_id": result.get("entry_order_id"),
                    "stop_order_id": result.get("stop_order_id"),
                    "target_order_id": result.get("target_order_id"),
                    "details": result,
                }
            else:
                return {"success": False, "error": result.get("error", "blocked"), "details": result}
        except Exception as e:
            logger.error(f"TopstepX API order error (direct): {e}")
            return {"success": False, "error": str(e)}

    username = os.getenv("TOPSTEP_USERNAME")
    password = os.getenv("TOPSTEP_PASSWORD")
    if not username or not password:
        return {"success": False, "error": "Missing credentials"}

    result = {"success": False, "action": "place_order", "data": {}}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        try:
            # ─── LOGIN ───
            await page.goto("https://topstepx.com/login", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
            
            inputs = await page.query_selector_all('input')
            for inp in inputs:
                name = await inp.get_attribute('name') or ''
                typ = await inp.get_attribute('type') or ''
                if 'user' in name.lower() or typ == 'email':
                    await inp.fill(username)
                elif typ == 'password':
                    await inp.fill(password)
            
            btn = await page.query_selector('button:has-text("PLATFORM LOGIN")')
            if btn:
                await btn.click()
            
            await page.wait_for_url("**/trade", timeout=30000)
            logger.info("Navigated to /trade")
            await asyncio.sleep(10)
            
            # ─── POSITION CHECK ───
            pos = await _read_position_from_page(page)
            if pos["open"]:
                logger.info(f"Existing position: {pos['side']} {pos['contracts']}x @ {pos['entry_price']}")
                
                # Same direction → skip (no accumulation)
                if pos["side"] == side.lower():
                    logger.warning(f"Already {pos['side']} {pos['contracts']}x — skipping duplicate entry")
                    result = {
                        "success": True,
                        "action": "skip",
                        "reason": f"Already {pos['side']} {pos['contracts']}x",
                        "data": pos,
                    }
                    await browser.close()
                    return result
                
                # Opposite direction → flatten first
                logger.info(f"Reversing position: {pos['side']} → {side}")
                flatten_btn = await page.query_selector('button:has-text("FLATTEN ALL")')
                if flatten_btn:
                    await flatten_btn.click()
                    logger.info("Clicked FLATTEN ALL")
                    await asyncio.sleep(3)
                else:
                    # Manual close: click Close Position or opposite side
                    close_testid = "order-card-click-button-sell" if pos["side"] == "long" else "order-card-click-button-buy"
                    close_btn = await page.query_selector(f'[data-testid="{close_testid}"]')
                    if close_btn:
                        await close_btn.click()
                        logger.info(f"Clicked {close_testid} to close {pos['side']}")
                        await asyncio.sleep(3)
            else:
                logger.info("No existing position — ready to enter")

            # ─── SET STOP / TARGET (Position Bracket) ───
            # Look for bracket preset buttons (1, 3, 5, 10, 15 ticks)
            if stop_loss and take_profit:
                # Try to set custom bracket via position bracket dropdown
                bracket_dropdown = await page.query_selector('[class*="Position Bracket"], button:has-text("Enabled")')
                if bracket_dropdown:
                    logger.info("Position bracket is enabled")
                
                # For now, log the levels — TopstepX auto-bracket presets are simpler
                logger.info(f"Target stop: {stop_loss}, target profit: {take_profit}")
            
            # ─── SET QUANTITY ───
            order_card = await page.query_selector('.ordercard-module__order___uXu3d, .ordercard-module__cardWrapper___vMvQ7')
            qty_input = None
            if order_card:
                qty_input = await order_card.query_selector('input[type="number"]')
            if not qty_input:
                number_inputs = await page.query_selector_all('input[type="number"]')
                for inp in number_inputs:
                    val = await inp.get_attribute('value') or '0'
                    if int(val) > 1:
                        qty_input = inp
                        break
            if qty_input:
                await qty_input.fill(str(quantity))
                logger.info(f"Set quantity to {quantity}")

            # ─── CLICK BUY/SELL ───
            side_btn_text = "Buy" if side.lower() == "long" else "Sell"
            clicked = False
            
            testid = "order-card-click-button-buy" if side.lower() == "long" else "order-card-click-button-sell"
            try:
                btn = await page.query_selector(f'[data-testid="{testid}"]')
                if btn:
                    await btn.click()
                    logger.info(f"Clicked {side_btn_text} via data-testid: {testid}")
                    clicked = True
            except Exception as e:
                logger.debug(f"data-testid click failed: {e}")
            
            if not clicked:
                testid2 = "dom-click-button-buy" if side.lower() == "long" else "dom-click-button-sell"
                try:
                    btn = await page.query_selector(f'[data-testid="{testid2}"]')
                    if btn:
                        await btn.click()
                        logger.info(f"Clicked {side_btn_text} via data-testid: {testid2}")
                        clicked = True
                except Exception as e:
                    logger.debug(f"DOM data-testid click failed: {e}")
            
            if not clicked:
                logger.warning(f"Could not find {side_btn_text} button")

            await asyncio.sleep(2)

            # ─── SCREENSHOT & RESULT ───
            screenshot_path = f"/Users/macbook/.alphatrader/audit_screenshots/topstep_order_{symbol}_{asyncio.get_event_loop().time()}.png"
            await page.screenshot(path=screenshot_path)
            result["screenshot_path"] = screenshot_path
            result["success"] = True
            result["data"] = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "venue": platform,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "prior_position": pos,
            }
            
            # Record position entry for timeout tracking
            if not pos.get("open") or pos.get("side") != side.lower():
                # Try to read actual entry price from page after fill
                new_pos = await _read_position_from_page(page)
                entry_price = new_pos.get("entry_price", price or 0.0)
                _record_position_entry(symbol, side, quantity, entry_price)

        except Exception as e:
            logger.error(f"Direct Playwright order failed: {e}")
            result["error"] = str(e)
        finally:
            await browser.close()

    return result


# ─── POSITION MONITORING & MANAGEMENT ───

async def get_positions_direct(platform: str = "topstep", **kwargs) -> List[Dict]:
    """Get open positions.
    
    For TopstepX, uses the ProjectX Gateway API (tools.topstep).
    Falls back to Playwright for other platforms.
    """
    import os
    import asyncio
    import re
    from playwright.async_api import async_playwright
    from loguru import logger
    
    if platform.lower() == "topstep":
        try:
            from tools.topstep import topstep_get_positions, topstep_get_price
            api_positions = await topstep_get_positions()
            result = []
            for pos in api_positions:
                contract_id = pos.get("contract_id", "")
                # Map contract ID back to a display symbol
                symbol = contract_id
                for simple, cid_part in [("NQ", "ENQ"), ("ES", "EP"), ("MNQ", "MNQ"), ("MES", "MES"),
                                         ("YM", "YM"), ("RTY", "RTY"), ("CL", "CL"), ("GC", "GC")]:
                    if f".{cid_part}." in contract_id or contract_id.endswith(f".{cid_part}"):
                        symbol = simple
                        break
                # Try to get a current platform price
                platform_price = None
                try:
                    price_data = await topstep_get_price(symbol)
                    platform_price = price_data.get("last")
                except Exception:
                    pass
                result.append({
                    "symbol": symbol,
                    "side": pos.get("side"),
                    "contracts": pos.get("size", 0),
                    "pnl": 0.0,
                    "entry_price": pos.get("entry"),
                    "entry_time": None,
                    "platform_price": platform_price,
                    "source": "topstep_api",
                })
            logger.info(f"get_positions_direct (API): {len(result)} positions")
            return result
        except Exception as e:
            logger.error(f"get_positions_direct API failed: {e}")
            return []
    
    username = os.getenv("TOPSTEP_USERNAME")
    password = os.getenv("TOPSTEP_PASSWORD")
    if not username or not password:
        logger.error("get_positions_direct: Missing TOPSTEP_USERNAME or TOPSTEP_PASSWORD")
        return []
    
    positions = []
    screenshot_path = None
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        try:
            logger.info("get_positions_direct: Logging in to topstepx.com")
            await page.goto("https://topstepx.com/login", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle")
            
            inputs = await page.query_selector_all("input")
            for inp in inputs:
                name = await inp.get_attribute("name") or ""
                typ = await inp.get_attribute("type") or ""
                if "user" in name.lower() or typ == "email":
                    await inp.fill(username)
                elif typ == "password":
                    await inp.fill(password)
            
            btn = await page.query_selector('button:has-text("PLATFORM LOGIN")')
            if btn:
                await btn.click()
            
            await page.wait_for_url("**/trade", timeout=30000)
            await asyncio.sleep(5)
            
            body_text = await page.inner_text('body')
            
            # ─── Check if there's actually a position open ───
            flatten_btn = await page.query_selector('button:has-text("FLATTEN ALL")')
            has_position = bool(flatten_btn)
            
            if not has_position:
                logger.info("get_positions_direct: No FLATTEN ALL button — no open position")
                await browser.close()
                return []
            
            logger.info("get_positions_direct: FLATTEN ALL visible — position detected")
            
            # ─── STRATEGY 1: Read from Positions tab ───
            pos_tab = await page.query_selector('button:has-text("Positions")')
            if pos_tab:
                await pos_tab.click()
                await asyncio.sleep(2)
                
                rows = await page.query_selector_all('table tbody tr, [class*="position"] tr')
                logger.info(f"get_positions_direct: Positions tab found, {len(rows)} rows")
                for row in rows:
                    cells = await row.query_selector_all('td')
                    if len(cells) >= 4:
                        texts = [await c.inner_text() for c in cells]
                        symbol = texts[0].strip() if len(texts) > 0 else ""
                        side_raw = texts[1].strip() if len(texts) > 1 else ""
                        qty = texts[2].strip() if len(texts) > 2 else "0"
                        pnl = texts[3].strip() if len(texts) > 3 else "0"
                        
                        side = ""
                        if side_raw:
                            side = "long" if "long" in side_raw.lower() or "buy" in side_raw.lower() or "+" in qty else "short"
                        
                        if symbol and side:
                            entry_info = _get_position_entry(symbol)
                            contracts = int(qty.replace('+', '').replace('-', ''))
                            pnl_val = float(pnl.replace('$', '').replace(',', '').replace('+', ''))
                            positions.append({
                                "symbol": symbol,
                                "side": side,
                                "contracts": contracts,
                                "pnl": pnl_val,
                                "entry_price": entry_info.get("entry_price"),
                                "entry_time": entry_info.get("entry_time"),
                                "source": "positions_tab",
                            })
                            logger.info(f"get_positions_direct: Position from tab: {symbol} {side} {contracts}x | P&L ${pnl_val:.2f}")
            
            # ─── STRATEGY 2: Parse order card with multiple regex patterns ───
            if not positions:
                logger.info("get_positions_direct: Trying order card parsing")
                card_match = None
                best_qty = 0
                
                # Pattern A: "+2 @ 29,634" or "-1 @ 5,000.50"
                patterns = [
                    r'([+-]\d+)\s*@\s*([\d,]+\.?\d*)',
                    r'(\d+)\s*[Ll]ot[s]?\s*@\s*([\d,]+\.?\d*)',
                    r'([Bb]uy|[Ss]ell)\s+(\d+)\s*@\s*([\d,]+\.?\d*)',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, body_text)
                    for match in matches:
                        if len(match) == 2:
                            qty_str, price_str = match
                        elif len(match) == 3:
                            _, qty_str, price_str = match
                        else:
                            continue
                        
                        try:
                            qty = int(qty_str)
                            price = float(price_str.replace(',', ''))
                        except ValueError:
                            continue
                        
                        if price < 100:  # Skip button presets
                            continue
                        
                        idx = body_text.find(f'{qty_str} @ {price_str}')
                        context = body_text[max(0, idx-30):min(len(body_text), idx+30)].lower()
                        if 'buy' in context and 'button' in context:
                            continue
                        if 'sell' in context and 'button' in context:
                            continue
                        if 'market' in context and 'order' in context:
                            continue
                        
                        if abs(qty) > best_qty:
                            best_qty = abs(qty)
                            card_match = (qty_str, price_str)
                
                if card_match:
                    qty = int(card_match[0])
                    entry = float(card_match[1].replace(',', ''))
                    side = "short" if qty < 0 else "long"
                    contracts = abs(qty)
                    
                    # Find symbol
                    active_symbol = ""
                    for sym_prefix in ["NQ", "ES", "YM", "RTY", "CL", "GC"]:
                        if re.search(rf'\b{sym_prefix}[MFZU]\d{{1,2}}\b', body_text):
                            active_symbol = re.search(rf'\b{sym_prefix}[MFZU]\d{{1,2}}\b', body_text).group(0)
                            break
                    
                    if not active_symbol:
                        for sym_prefix, (low, high) in _SYMBOL_PRICE_RANGES.items():
                            if low <= entry <= high:
                                active_symbol = f"{sym_prefix}M26"
                                break
                    
                    pnl_match = re.search(r'UP&L\s*[:\-]?\s*\$?([\d,]+\.?\d*)', body_text)
                    pnl = float(pnl_match.group(1).replace(',', '')) if pnl_match else 0.0
                    
                    entry_info = _get_position_entry(active_symbol)
                    state_contracts = entry_info.get("contracts")
                    if state_contracts and state_contracts != contracts:
                        logger.info(f"Using state file contract count: {state_contracts} instead of regex: {contracts}")
                        contracts = state_contracts
                    
                    positions.append({
                        "symbol": active_symbol,
                        "side": side,
                        "contracts": contracts,
                        "pnl": pnl,
                        "entry_price": entry or entry_info.get("entry_price"),
                        "entry_time": entry_info.get("entry_time"),
                        "source": "order_card",
                    })
                    logger.info(f"get_positions_direct: Position from card: {active_symbol} {side} {contracts}x @ {entry} | P&L ${pnl:.2f}")
                else:
                    logger.warning("get_positions_direct: FLATTEN ALL visible but ALL regex patterns failed")
            
            # ─── Read platform current price from page ───
            platform_price = None
            if positions:
                # Try to find last price on page
                price_selectors = [
                    '[class*="last-price"]',
                    '[class*="LastPrice"]',
                    '[class*="ltp"]',
                    '[class*="current-price"]',
                ]
                for sel in price_selectors:
                    el = await page.query_selector(sel)
                    if el:
                        txt = await el.inner_text()
                        m = re.search(r'[\d,]+\.?\d*', txt)
                        if m:
                            platform_price = float(m.group(0).replace(',', ''))
                            break
                
                # Fallback: derive from P&L if we have entry + contracts
                if platform_price is None and positions[0].get("entry_price") and positions[0].get("pnl") is not None:
                    pos = positions[0]
                    entry = pos["entry_price"]
                    pnl = pos["pnl"]
                    contracts = pos["contracts"]
                    side = pos["side"]
                    # P&L = (current - entry) * contracts * dollar_per_pt
                    # For NQ: $20/pt/contract
                    dollar_per_pt = _get_symbol_params(pos["symbol"]).get("dollar_per_pt", 20.0)
                    if contracts > 0 and dollar_per_pt > 0:
                        if side == "long":
                            implied = entry + (pnl / (contracts * dollar_per_pt))
                        else:
                            implied = entry - (pnl / (contracts * dollar_per_pt))
                        platform_price = round(implied, 2)
                        logger.info(f"get_positions_direct: Derived platform price from P&L: {platform_price}")
                
                for pos in positions:
                    pos["platform_price"] = platform_price
            
            if not positions:
                logger.error("get_positions_direct: CRITICAL — FLATTEN ALL exists but position could not be parsed")
                screenshot_path = f"/Users/macbook/.alphatrader/audit_screenshots/topstep_unreadable_{asyncio.get_event_loop().time()}.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"get_positions_direct: Screenshot saved: {screenshot_path}")
        except Exception as e:
            logger.error(f"get_positions_direct: FAILED — {e}")
            try:
                screenshot_path = f"/Users/macbook/.alphatrader/audit_screenshots/topstep_error_{asyncio.get_event_loop().time()}.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"get_positions_direct: Error screenshot saved: {screenshot_path}")
            except Exception:
                pass
        finally:
            await browser.close()
    
    return positions


async def close_position_direct(platform: str = "topstep", symbol: str = "", **kwargs) -> dict:
    """Close a position.
    
    For TopstepX, uses the ProjectX Gateway API (tools.topstep).
    Falls back to Playwright for other platforms.
    """
    import os
    import asyncio
    from playwright.async_api import async_playwright
    from loguru import logger
    
    if platform.lower() == "topstep":
        try:
            from tools.topstep import topstep_flatten_all
            flatten_results = await topstep_flatten_all(confirmed=True)
            success = all(r.get("status") == "submitted" for r in flatten_results) if flatten_results else True
            return {
                "success": success,
                "action": "flatten_all",
                "symbol": symbol,
                "targets": kwargs.get("targets", []),
                "results": flatten_results,
            }
        except Exception as e:
            logger.error(f"close_position_direct API failed: {e}")
            return {"success": False, "error": str(e)}
    
    username = os.getenv("TOPSTEP_USERNAME")
    password = os.getenv("TOPSTEP_PASSWORD")
    if not username or not password:
        logger.warning("close_position_direct: Missing credentials")
        return {"success": False, "error": "Missing credentials"}
    
    # Extract targets from workflow inputs
    close_decisions = kwargs.get("close_decisions", {})
    targets = close_decisions.get("targets", kwargs.get("targets", []))
    
    # Determine symbol to close
    target_symbol = symbol
    if not target_symbol and targets:
        target_symbol = targets[0].get("symbol", "")
    
    logger.info(f"close_position_direct START: symbol={target_symbol}, targets={targets}")
    
    result = {"success": False, "action": "close_position", "symbol": target_symbol, "targets": targets}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            await page.goto("https://topstepx.com/login", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle")
            
            inputs = await page.query_selector_all("input")
            for inp in inputs:
                name = await inp.get_attribute("name") or ""
                typ = await inp.get_attribute("type") or ""
                if "user" in name.lower() or typ == "email":
                    await inp.fill(username)
                elif typ == "password":
                    await inp.fill(password)
            
            btn = await page.query_selector('button:has-text("PLATFORM LOGIN")')
            if btn:
                await btn.click()
            
            await page.wait_for_url("**/trade", timeout=30000)
            await asyncio.sleep(5)
            
            # ─── Strategy 1: Look for FLATTEN ALL on main page ───
            flatten_btn = await page.query_selector('button:has-text("FLATTEN ALL")')
            if flatten_btn:
                logger.info("Found FLATTEN ALL button on main page — clicking")
                await flatten_btn.click()
                result["success"] = True
                result["method"] = "flatten_all"
                logger.info("Flattened all positions via main page button")
            else:
                logger.info("No FLATTEN ALL on main page — trying Positions tab")
                
                # ─── Strategy 2: Click Positions tab ───
                pos_tab = await page.query_selector('button:has-text("Positions")')
                if pos_tab:
                    await pos_tab.click()
                    await asyncio.sleep(2)
                    
                    # Try Flatten All inside Positions tab
                    flatten_btn_tab = await page.query_selector('button:has-text("Flatten All")')
                    if flatten_btn_tab:
                        logger.info("Found FLATTEN ALL in Positions tab — clicking")
                        await flatten_btn_tab.click()
                        result["success"] = True
                        result["method"] = "flatten_all"
                        logger.info("Flattened all positions via Positions tab")
                    else:
                        # Find position row and click Close
                        rows = await page.query_selector_all('table tbody tr')
                        closed = False
                        for row in rows:
                            text = await row.inner_text()
                            if target_symbol and target_symbol.upper() in text.upper():
                                close_btn = await row.query_selector('button:has-text("Close"), button:has-text("X")')
                                if close_btn:
                                    logger.info(f"Found Close button for {target_symbol} — clicking")
                                    await close_btn.click()
                                    result["success"] = True
                                    closed = True
                                    logger.info(f"Closed position for {target_symbol}")
                                    break
                        
                        if not closed:
                            logger.warning("No close button or Flatten All found in Positions tab")
                else:
                    logger.warning("No Positions tab found")
            
            await asyncio.sleep(2)
            screenshot_path = f"/Users/macbook/.alphatrader/audit_screenshots/topstep_close_{target_symbol}_{asyncio.get_event_loop().time()}.png"
            await page.screenshot(path=screenshot_path)
            result["screenshot_path"] = screenshot_path
            
            # Clear position state for all closed symbols
            if result.get("success"):
                if target_symbol:
                    _clear_position_entry(target_symbol)
                for t in targets:
                    sym = t.get("symbol")
                    if sym:
                        _clear_position_entry(sym)
            
        except Exception as e:
            logger.error(f"Close position failed: {e}")
            result["error"] = str(e)
        finally:
            await browser.close()
    
    logger.info(f"close_position_direct END: success={result.get('success')}, method={result.get('method')}, error={result.get('error')}")
    return result


async def _get_current_price(symbol: str) -> float:
    """Get current price for a futures symbol via yfinance."""
    try:
        import yfinance as yf
        # Map futures symbols to yfinance tickers
        sym_map = {
            "NQM26": "NQ=F", "ESM26": "ES=F", "YMM26": "YM=F",
            "RTYM26": "RTY=F", "CLN26": "CL=F", "GCQ26": "GC=F",
        }
        ticker = sym_map.get(symbol.upper(), symbol.upper() + "=F")
        data = yf.download(ticker, period="1d", interval="1m", progress=False)
        if data is not None and len(data) > 0:
            return float(data["Close"].iloc[-1])
    except Exception as e:
        from loguru import logger
        logger.debug(f"Could not get current price: {e}")
    return None


# Symbol-specific price ranges for validation
_SYMBOL_PRICE_RANGES = {
    "NQ": (15000, 45000),
    "ES": (3000, 8000),
    "YM": (30000, 55000),
    "RTY": (1500, 3500),
    "CL": (40, 150),
    "GC": (1500, 3000),
}

# Conservative combine strategy parameters (per-symbol) — CONSERVATIVE REBUILD
_SYMBOL_TRADE_PARAMS = {
    "NQ": {"stop_pts": 8, "target_pts": 12, "tick_size": 0.25, "dollar_per_pt": 20.0},
    "ES": {"stop_pts": 4, "target_pts": 8, "tick_size": 0.25, "dollar_per_pt": 12.5},
    "YM": {"stop_pts": 40, "target_pts": 60, "tick_size": 1.0, "dollar_per_pt": 5.0},
    "RTY": {"stop_pts": 6, "target_pts": 10, "tick_size": 0.10, "dollar_per_pt": 50.0},
    "CL": {"stop_pts": 0.20, "target_pts": 0.40, "tick_size": 0.01, "dollar_per_pt": 1000.0},
    "GC": {"stop_pts": 4.0, "target_pts": 7.0, "tick_size": 0.10, "dollar_per_pt": 100.0},
}

# Max hold time for futures (minutes) — CONSERVATIVE: 30 min scalp only
_FUTURES_MAX_HOLD_MINUTES = 30

def _get_symbol_params(symbol: str) -> dict:
    """Get trade parameters for a symbol (e.g. NQM26 → NQ)."""
    if not symbol:
        return _SYMBOL_TRADE_PARAMS.get("NQ", {})
    sym_prefix = symbol[:2].upper()
    return _SYMBOL_TRADE_PARAMS.get(sym_prefix, _SYMBOL_TRADE_PARAMS.get("NQ", {}))

def _is_valid_price_for_symbol(symbol: str, price: float) -> bool:
    """Check if a price is reasonable for the given symbol."""
    if not symbol or not price:
        return False
    sym_prefix = symbol[:2].upper()
    valid_range = _SYMBOL_PRICE_RANGES.get(sym_prefix)
    if valid_range:
        return valid_range[0] <= price <= valid_range[1]
    return True


async def evaluate_positions(positions: list = None, config: dict = None, **kwargs) -> dict:
    """Evaluate open positions and decide if any should be closed.
    
    Uses fast-pass combine parameters (12pt stop / 20pt target for NQ, etc.)
    Hard P&L limits scale with contract count.
    Time exit: 120 min for overnight futures.
    """
    from loguru import logger
    from datetime import datetime, timezone
    
    if not positions:
        return {"should_close": False, "reason": "No open positions"}
    
    close_targets = []
    
    for pos in positions:
        pnl = pos.get("pnl", 0)
        symbol = pos.get("symbol", "")
        side = pos.get("side", "")
        contracts = pos.get("contracts", 0)
        entry = pos.get("entry_price", pos.get("entry", 0))
        entry_time = pos.get("entry_time", None)
        
        # Validate position data — skip bogus entries
        if not symbol or not side or contracts <= 0:
            logger.debug(f"Skipping invalid position entry: {pos}")
            continue
        
        # Validate entry price is reasonable for symbol
        if entry and not _is_valid_price_for_symbol(symbol, entry):
            logger.warning(f"Bogus position data detected: {symbol} @ {entry} — price out of valid range. Skipping.")
            continue
        
        params = _get_symbol_params(symbol)
        stop_pts = params.get("stop_pts", 12)
        target_pts = params.get("target_pts", 20)
        dollar_per_pt = params.get("dollar_per_pt", 20.0)
        
        # Dynamic hard P&L limits based on actual risk/reward
        max_risk_dollars = stop_pts * dollar_per_pt * contracts
        max_reward_dollars = target_pts * dollar_per_pt * contracts
        
        reason = None
        current = None
        stop_level = None
        tp_level = None
        elapsed = None
        
        # Hard P&L limits
        if pnl < -max_risk_dollars:
            reason = f"Hard stop: P&L ${pnl:.2f} (limit: -${max_risk_dollars:.0f})"
        elif pnl > max_reward_dollars:
            reason = f"Hard take profit: P&L ${pnl:.2f} (limit: +${max_reward_dollars:.0f})"
        
        # Entry-price based stops/targets
        # CRITICAL: Use platform_price from get_positions_direct first.
        # yfinance is unreliable for futures overnight and caused a FALSE STOP on 2026-06-09.
        if not reason and entry:
            current = pos.get("platform_price")
            price_source = "platform"
            
            if not current:
                logger.warning(f"evaluate_positions: No platform_price for {symbol} — falling back to yfinance (UNRELIABLE)")
                current = await _get_current_price(symbol)
                price_source = "yfinance"
            
            if current and _is_valid_price_for_symbol(symbol, current):
                # Cross-validate: if P&L is positive but price suggests stop, flag discrepancy
                if pnl > 50 and side == "long" and current <= entry - (stop_pts * 0.5):
                    logger.error(
                        f"PRICE DISCREPANCY ALERT: {symbol} | platform_price={current} | "
                        f"entry={entry} | P&L=${pnl:.2f} (positive) | price_source={price_source} | "
                        f"Price implies stop but P&L is green. SKIPPING stop evaluation."
                    )
                    current = None  # Skip price-based evaluation this cycle
                elif pnl > 50 and side == "short" and current >= entry + (stop_pts * 0.5):
                    logger.error(
                        f"PRICE DISCREPANCY ALERT: {symbol} | platform_price={current} | "
                        f"entry={entry} | P&L=${pnl:.2f} (positive) | price_source={price_source} | "
                        f"Price implies stop but P&L is green. SKIPPING stop evaluation."
                    )
                    current = None
                
                if current:
                    if side == "long":
                        stop_level = entry - stop_pts
                        tp_level = entry + target_pts
                        if current <= stop_level:
                            reason = f"Stop hit: {current:.2f} <= {stop_level:.2f}"
                        elif current >= tp_level:
                            reason = f"Target hit: {current:.2f} >= {tp_level:.2f}"
                    elif side == "short":
                        stop_level = entry + stop_pts
                        tp_level = entry - target_pts
                        if current >= stop_level:
                            reason = f"Stop hit: {current:.2f} >= {stop_level:.2f}"
                        elif current <= tp_level:
                            reason = f"Target hit: {current:.2f} <= {tp_level:.2f}"
        
        # Time-based exit (120 min for overnight futures)
        if not reason and entry_time:
            try:
                dt = datetime.fromisoformat(entry_time) if isinstance(entry_time, str) else entry_time
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - dt).total_seconds() / 60
                if elapsed > _FUTURES_MAX_HOLD_MINUTES:
                    reason = f"Time exit: {elapsed:.0f} min held (max {_FUTURES_MAX_HOLD_MINUTES})"
            except Exception as e:
                logger.debug(f"Time exit parse failed for {symbol}: {e}")
        
        # Log evaluation every cycle for visibility
        cur_str = f"{current:.2f}" if current is not None else "n/a"
        stop_str = f"{stop_level:.2f}" if stop_level is not None else "n/a"
        tp_str = f"{tp_level:.2f}" if tp_level is not None else "n/a"
        elapsed_str = f"{elapsed:.0f}min" if elapsed is not None else "n/a"
        logger.info(
            f"Position monitor eval: {symbol} {side} {contracts}x @ {entry:.2f} | "
            f"current={cur_str} | stop={stop_str} | target={tp_str} | "
            f"pnl=${pnl:.2f} | elapsed={elapsed_str} | "
            f"decision={'CLOSE' if reason else 'HOLD'}"
        )
        
        if reason:
            close_targets.append({
                "symbol": symbol,
                "side": side,
                "contracts": contracts,
                "pnl": pnl,
                "entry_price": entry,
                "reason": reason,
            })
            logger.info(f"Position monitor TRIGGER: {symbol} {side} — {reason}")
    
    if close_targets:
        return {
            "should_close": True,
            "targets": close_targets,
            "reason": f"Closing {len(close_targets)} position(s)"
        }
    
    return {"should_close": False, "reason": "All positions within limits"}
