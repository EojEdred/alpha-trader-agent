"""
Base Browser Agent

Rewritten for browser-use 0.12 (CDP-based).

Key features:
- True session persistence via Chrome user_data_dir + storage_state
- Dynamic model selection via LLMFactory
- Dry-run mode: navigates but never submits orders
- 2FA/CAPTCHA detection with human-in-the-loop
- Screenshot audit trail via native CDP

Session Persistence Architecture:
===============================
1. BrowserSession is created ONCE with user_data_dir pointing to
   ~/.alphatrader/browser_sessions/{platform}/
2. Chrome persists cookies, localStorage, sessionStorage in this dir
3. After each task, we explicitly save storage_state to JSON
4. On next initialize(), we restore storage_state if within TTL
5. Multiple Agent instances reuse the SAME BrowserSession

This means:
- Login once, stay logged in across tasks
- 2FA only needed once per session TTL (default 24h)
- Prop firm platforms see consistent session, not repeated logins
"""

import os
import json
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger


@dataclass
class BrowserActionResult:
    """Result of a browser automation action."""
    success: bool
    action: str
    data: Dict[str, Any] = field(default_factory=dict)
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


class BaseBrowserAgent(ABC):
    """
    Base class for browser-based trading automation.
    
    Uses browser-use 0.12 CDP-based API with persistent sessions.
    """
    
    def __init__(
        self,
        platform_name: str,
        model: Optional[str] = None,
        headless: bool = False,
        slow_mo: int = 100,
        session_ttl_hours: float = 24.0,
        dry_run: bool = False,
    ):
        self.platform_name = platform_name
        self.model = model or os.getenv("BROWSER_USE_MODEL", "gpt-4o")
        self.headless = headless
        self.slow_mo = slow_mo
        self.session_ttl_hours = session_ttl_hours
        self.dry_run = dry_run
        
        # Session state
        self._browser_session = None
        self._llm = None
        self._initialized = False
        self._session_start = None
        
        # Session persistence paths
        self._session_dir = Path.home() / ".alphatrader" / "browser_sessions" / platform_name
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._storage_state_file = self._session_dir / "storage_state.json"
        self._session_meta_file = self._session_dir / "session_meta.json"
        
        # Action history for audit
        self.action_history: List[BrowserActionResult] = []
        
        # 2FA handler
        from tools.two_factor_handler import TwoFactorHandler
        self._2fa_handler = TwoFactorHandler()
        
        logger.info(f"BrowserAgent[{platform_name}] initialized (model={self.model}, dry_run={dry_run})")
    
    # ─── SESSION PERSISTENCE ───
    
    async def initialize(self):
        """Initialize browser session with persistence."""
        if self._initialized:
            return
        
        try:
            from browser_use import BrowserSession
            from tools.llm_factory import LLMFactory
            
            # Check if previous session is still valid
            storage_state = self._load_storage_state()
            
            # Create browser session with persistent profile
            self._browser_session = BrowserSession(
                headless=self.headless,
                user_data_dir=str(self._session_dir),
                storage_state=storage_state,
                wait_between_actions=self.slow_mo / 1000.0,  # Convert ms to seconds
            )
            
            # Create LLM via factory — discover dynamically
            factory = LLMFactory.discover()
            self._llm = factory.create(self.model)

            # Warn if using kimi CLI wrapper — it's not ideal for browser automation
            from tools.llm_factory import KimiCLIWrapper
            if isinstance(self._llm, KimiCLIWrapper):
                logger.warning(
                    "BrowserAgent using KimiCLIWrapper — this is best for simple tasks. "
                    "For reliable browser automation, use kimi-k2 via API (set KIMI_API_KEY)."
                )

            self._initialized = True
            self._session_start = datetime.utcnow()
            
            # Save session metadata
            self._save_session_meta()
            
            logger.info(f"BrowserAgent[{self.platform_name}] session initialized (storage_state={'restored' if storage_state else 'fresh'})")
            
        except Exception as e:
            logger.error(f"Failed to initialize browser agent: {e}")
            raise
    
    async def shutdown(self):
        """Clean shutdown with session persistence."""
        if self._browser_session:
            try:
                # Explicitly save storage state before closing
                await self._save_storage_state()
                await self._browser_session.stop()
                logger.info(f"BrowserAgent[{self.platform_name}] session saved and stopped")
            except Exception as e:
                logger.warning(f"Error during shutdown: {e}")
        
        self._initialized = False
        self._browser_session = None
    
    def _load_storage_state(self) -> Optional[Dict]:
        """Load previous storage state if within TTL."""
        if not self._storage_state_file.exists():
            return None
        
        try:
            # Check TTL
            if self._session_meta_file.exists():
                meta = json.loads(self._session_meta_file.read_text())
                last_active = datetime.fromisoformat(meta.get("last_active", "2000-01-01"))
                if datetime.utcnow() - last_active > timedelta(hours=self.session_ttl_hours):
                    logger.info(f"Session expired for {self.platform_name}, starting fresh")
                    return None
            
            state = json.loads(self._storage_state_file.read_text())
            logger.info(f"Restored storage state for {self.platform_name}")
            return state
        except Exception as e:
            logger.warning(f"Failed to load storage state: {e}")
            return None
    
    async def _save_storage_state(self):
        """Save current storage state for next session."""
        try:
            if self._browser_session and hasattr(self._browser_session, 'context'):
                # Get storage state from Playwright context
                context = self._browser_session.context
                if context:
                    state = await context.storage_state()
                    self._storage_state_file.write_text(json.dumps(state, indent=2))
                    self._save_session_meta()
                    logger.debug(f"Saved storage state for {self.platform_name}")
        except Exception as e:
            logger.warning(f"Failed to save storage state: {e}")
    
    def _save_session_meta(self):
        """Save session metadata."""
        meta = {
            "last_active": datetime.utcnow().isoformat(),
            "platform": self.platform_name,
            "model": self.model,
        }
        self._session_meta_file.write_text(json.dumps(meta, indent=2))
    
    # ─── TASK EXECUTION ───
    
    async def run_task(self, task: str, max_steps: int = 30) -> BrowserActionResult:
        """
        Execute a natural language task via browser-use agent.
        
        Reuses the same BrowserSession across calls for true persistence.
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            from browser_use import Agent
            
            # Add human-like behavior instructions
            enhanced_task = f"""
            {task}
            
            IMPORTANT BEHAVIOR RULES:
            - Wait for pages to fully load before interacting
            - If a button is not clickable, wait 2 seconds and retry
            - Take screenshots at key steps for verification
            - If you see a CAPTCHA or 2FA prompt, STOP and report it
            - Do not click random links - only interact with trading-related elements
            - Scroll slowly and naturally if needed
            """
            
            # Create agent with shared browser session
            agent = Agent(
                task=enhanced_task,
                llm=self._llm,
                browser_session=self._browser_session,
                use_vision=True,
            )
            
            result = await agent.run(max_steps=max_steps)
            
            # Check for 2FA/CAPTCHA in result
            if self._detect_challenge_in_result(result):
                challenge_resolved = await self._2fa_handler.detect_challenge(self)
                if challenge_resolved:
                    resolved = await self._2fa_handler.wait_for_resolution(self)
                    if not resolved:
                        return BrowserActionResult(
                            success=False,
                            action=task,
                            error="2FA/CAPTCHA challenge timed out",
                        )
            
            # Extract result data
            result_data = {"result": str(result)}
            if hasattr(result, 'all_results') and result.all_results:
                last_result = result.all_results[-1]
                result_data["last_extracted"] = last_result.extracted_content if hasattr(last_result, 'extracted_content') else ""
            
            action_result = BrowserActionResult(
                success=True,
                action=task,
                data=result_data,
            )
            
            self.action_history.append(action_result)
            logger.info(f"BrowserAgent[{self.platform_name}] task completed: {task[:50]}...")
            return action_result
            
        except Exception as e:
            logger.error(f"BrowserAgent[{self.platform_name}] task failed: {e}")
            action_result = BrowserActionResult(
                success=False,
                action=task,
                error=str(e),
            )
            self.action_history.append(action_result)
            return action_result
    
    def _detect_challenge_in_result(self, result) -> bool:
        """Detect if agent result indicates a challenge."""
        result_str = str(result).lower()
        challenge_indicators = [
            "2fa", "two-factor", "captcha", "security question",
            "verify", "authentication", "login required",
        ]
        return any(ind in result_str for ind in challenge_indicators)
    
    # ─── SCREENSHOTS ───
    
    async def screenshot(self, filename: Optional[str] = None) -> str:
        """Capture screenshot using native CDP and save to audit directory."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = filename or f"screenshot_{self.platform_name}_{timestamp}.png"
        
        # Save to persistent audit directory
        audit_dir = Path.home() / ".alphatrader" / "audit_screenshots"
        audit_dir.mkdir(parents=True, exist_ok=True)
        filepath = audit_dir / filename
        
        try:
            if self._browser_session:
                # Use browser-use's screenshot capability
                # Get the current page from the session
                page = await self._get_current_page()
                if page:
                    await page.screenshot(path=str(filepath), full_page=False)
                    logger.debug(f"Screenshot saved: {filepath}")
                    return str(filepath)
            
            # Fallback: try via agent task
            result = await self.run_task(
                f"Take a screenshot and save it to the file '{filepath}'. "
                f"Confirm the screenshot was saved successfully.",
                max_steps=5
            )
            if result.success:
                return str(filepath)
            return ""
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return ""
    
    async def _get_current_page(self):
        """Get the current active page from the browser session."""
        try:
            if hasattr(self._browser_session, 'context'):
                context = self._browser_session.context
                if context:
                    pages = context.pages
                    if pages:
                        return pages[-1]  # Most recent page
            return None
        except Exception:
            return None
    
    # ─── SAFE INTERACTIONS ───
    
    async def safe_click(self, selector: str, description: str = "") -> bool:
        """Safely click an element with retry."""
        try:
            result = await self.run_task(
                f"Find and click the element matching '{selector}' ({description}). "
                f"Wait for it to be visible and clickable first. Confirm the click succeeded.",
                max_steps=10
            )
            return result.success
        except Exception as e:
            logger.error(f"Click failed on {selector}: {e}")
            return False
    
    async def safe_type(self, selector: str, text: str, description: str = "") -> bool:
        """Safely type into an input with retry."""
        try:
            result = await self.run_task(
                f"Find the input field matching '{selector}' ({description}). "
                f"Click it, clear any existing text, and type exactly: '{text}'. "
                f"Confirm the text was entered correctly.",
                max_steps=10
            )
            return result.success
        except Exception as e:
            logger.error(f"Type failed on {selector}: {e}")
            return False
    
    async def read_text(self, selector: str, description: str = "") -> str:
        """Read text from an element."""
        try:
            result = await self.run_task(
                f"Find the element matching '{selector}' ({description}) and read its text content. "
                f"Return ONLY the text content, nothing else.",
                max_steps=5
            )
            if result.success:
                return result.data.get("result", "")
            return ""
        except Exception as e:
            logger.error(f"Read failed on {selector}: {e}")
            return ""
    
    # ─── DRY RUN ───
    
    async def dry_run_place_order(self, order: Dict[str, Any]) -> BrowserActionResult:
        """
        Dry-run order placement: navigate, fill ticket, screenshot, but DO NOT submit.
        
        This is used for testing and validation without executing live trades.
        """
        symbol = order.get("symbol", "")
        side = order.get("side", "long")
        quantity = int(order.get("quantity", 1))
        order_type = order.get("order_type", "market")
        
        task = f"""
        DRY RUN — Do NOT actually submit any order!
        
        1. Navigate to the trading interface for {symbol}
        2. Open the order ticket
        3. Fill in ALL order details:
           - Symbol: {symbol}
           - Side: {side}
           - Quantity: {quantity}
           - Order Type: {order_type.upper()}
        4. STOP before clicking "Submit" or "Place Order"
        5. Take a screenshot of the completed order ticket
        6. Report: "DRY RUN COMPLETE — Order ready but NOT submitted"
        
        IMPORTANT: Do NOT click any submit/place/confirm button!
        """
        
        result = await self.run_task(task, max_steps=20)
        
        # Add dry-run metadata
        result.data["dry_run"] = True
        result.data["order"] = order
        
        if result.success:
            screenshot = await self.screenshot(f"dryrun_{symbol}_{datetime.utcnow().strftime('%H%M%S')}.png")
            result.screenshot_path = screenshot
            logger.info(f"DRY RUN complete for {symbol} — order NOT submitted")
        
        return result
    
    # ─── ABSTRACT METHODS ───
    
    @abstractmethod
    async def login(self, credentials: Dict[str, str]) -> BrowserActionResult:
        """Log into the platform. Must be implemented by subclasses."""
        pass
    
    @abstractmethod
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions. Must be implemented by subclasses."""
        pass
    
    @abstractmethod
    async def place_order(self, order: Dict[str, Any]) -> BrowserActionResult:
        """
        Place an order. Must be implemented by subclasses.
        
        Args:
            order: Dict with keys:
                - symbol: str
                - side: str ("long" or "short")
                - quantity: int
                - order_type: str ("market", "limit", "stop")
                - price: Optional[float] (for limit/stop orders)
                - stop_loss: Optional[float]
                - take_profit: Optional[float]
                - time_in_force: str ("day", "gtc", etc.)
                - order_subtype: str (for Schwab: "equity", "option", "spread")
                - underlying: Optional[str] (for options)
                - option_symbol: Optional[str] (for options)
                - spread_type: Optional[str] (for spreads)
                - legs: Optional[List[Dict]] (for multi-leg orders)
                - net_credit_or_debit: Optional[float] (for spreads)
        """
        pass
    
    def get_action_history(self) -> List[BrowserActionResult]:
        """Get history of all actions for audit."""
        return self.action_history
